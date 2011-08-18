import uuid
import time
import tempfile
import logging

from boto.ec2.connection import EC2Connection
from fabulaws.ssh import SSH

logger = logging.getLogger('fabulaws.ec2')

class EC2Instance(object):
    """
    Base class for EC2 instances.
    """
    ami = ''
    user = ''
    instance_type = ''
    security_groups = []
    key_prefix = ''

    def __init__(self, key_id, secret):
        if not self.ami or not self.user or not self.instance_type:
            raise Exception('You must extend this class and define the ami, '
                            'user, and instance_type class variables.')
        # ensure these attributes exist
        self.conn = self.key = self.key_file = self.instance = self.ssh = None
        self._key_id = key_id
        self._secret = secret

    def _connect_ec2(self):
        logger.info('Connecting to EC2')
        return EC2Connection(self._key_id, self._secret)

    def _create_key_pair(self):
        """
        Creates a temporary key pair for connecting to this instance. The key
        pair is destroyed when exiting the context manager or destroying this
        object.
        """
        logger.info('Creating key pair')
        key_name = '{0}{1}'.format(self.key_prefix, uuid.uuid4())
        key = self.conn.create_key_pair(key_name)
        try:
            logger.debug('Created key pair {0}'.format(key_name))
            key_file = tempfile.NamedTemporaryFile()
            key_file.write(key.material)
            # make sure the data is there when read by SSH
            key_file.flush()
            logger.debug('Wrote key file {0}'.format(key_file.name))
        except:
            logger.info('Deleting key early due to unexpected exception')
            key.delete()
            raise
        return key, key_file

    def _create_instance(self):
        """
        Creates a new EC2 instance.  The instance is destroyed when exiting the
        context manager or destroying this object.
        """
        logger.info('Creating EC2 instance')
        image = self.conn.get_image(self.ami)
        res = image.run(key_name=self.key.name,
                        security_groups=self.security_groups,
                        instance_type=self.instance_type)
        inst = res.instances[0]
        logger.debug('Created EC2 instance {0}'.format(inst.id))
        try:
            logger.info('Waiting for instance to enter "running" state...')
            time.sleep(5) 
            while inst.update() != 'running':
                time.sleep(2)
        except:
            logger.info('Terminating instance early due to unexpected error')
            inst.terminate()
            raise
        return inst

    def _connect_instance(self):
        """
        Establishes a Paramiko SSHClient connection to this instance.
        """
        logger.info('Establishing SSH connection')
        pkey = paramiko.RSAKey.from_private_key(StringIO(self.key.material))
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        times = 0
        wait = 2
        while times < 120/wait:
            try:
                ssh.connect(self.instance.public_dns_name, allow_agent=False,
                            look_for_keys=False, username=self.user,
                            #pkey=pkey,
                            key_filename=self.key_file.name)
                break
            except socket.error, e:
                if e.errno in (110, 111): # Connection timed out & refused
                    logger.debug('Error connecting, retrying in {0} '
                                 'seconds'.format(wait))
                    times += 1
                    time.sleep(wait)
                else:
                    raise
        ssh.exec_command('ls')
        return ssh

    def _setup_context(self):
        """
        Sets up the Fabric context so commands can be run on this instance.
        """
        logger.info('Setting up context')
        self._saved_context = {}
        for attr in 'key_filename', 'user', 'host_string':
            self._saved_context[attr] = getattr(env, attr)
        logger.debug('Setting env.key_filename = "{0}"'
                     ''.format(self.key_file.name))
        env.key_filename = [self.key_file.name]
        logger.debug('Setting env.user = "{0}"'.format(self.user))
        env.user = self.user
        logger.debug('Setting env.host_string = "{0}"'
                     ''.format(self.instance.public_dns_name))
        env.host_string = self.instance.public_dns_name

    def _restore_context(self):
        """
        Restores the original Fabric context.
        """
        logger.info('Restoring context')
        for key, value in self._saved_context.items():
            setattr(env, key, value)

    def setup(self):
        """
        Creates the instance and sets up the Fabric context.  Extend this
        method in your subclass to further customize the instance.
        """
        self.conn = self._connect_ec2()
        self.key, self.key_file = self._create_key_pair()
        self.instance = self._create_instance()
        self.ssh = SSH(self.instance.public_dns_name, self.user,
                       self.key_file.name)
        #self._setup_context()

    def cleanup(self):
        """
        Destroys resources on EC2 created during the setup of this instance,
        including the instance itself.  Extend this method in your subclass
        to remove any additional resources your subclass may have created.
        """
        if self.key:
            logger.debug('Deleting key {0}'.format(self.key.name))
            self.key.delete()
            self.key = None
        if self.instance:
            logger.debug('Terminating instance {0}'.format(self.instance.id))
            self.instance.terminate()
            self.instance = None
        if self.key_file:
            logger.debug('Deleting key file {0}'.format(self.key_file.name))
            self.key_file.close()
            self.key_file = None
        if self.ssh:
            logger.debug('Destroying SSH connection')
            del self.ssh
            self.ssh = None

    def __enter__(self):
        self.setup()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.cleanup()
        #self._restore_context()

    def __del__(self):
        self.cleanup()


class UbuntuInstance(EC2Instance):
    """
    Base class for all Ubuntu instances.
    """
    user = 'ubuntu'
    volume_info = [] # tuples of (device, mount_point, size_in_GB)
    fs_type = 'ext3'
    fs_encrypt = True
    run_upgrade = True
    
    def __init__(self, key_id, secret):
        super(UbuntuInstance, self).__init__(key_id, secret)
        self.volumes = []

    def _create_volume(self, device, mount_point, vol_size):
        """
        Creates an EBS volume of size ``vol_size``, manifests the device at
        ``device`` in this instance, and mounts it at ``mount_point``.
        """
        logger.info('Attaching {0}'.format(device))
        inst = self.instance
        # the placement is the availability zone
        vol = self.conn.create_volume(vol_size, inst.placement)
        try:
            vol.attach(inst.id, device)
            logger.debug('Waiting for volume {0} to become '
                         'attached'.format(vol.id))
            while vol.volume_state() == 'creating':
                time.sleep(1)
                vol.update()
            logger.debug('volume state: {0}'.format(vol.volume_state()))
            if self.fs_encrypt:
                self.ssh.sudo('apt-get install -y pwgen cryptsetup')
                logger.debug('volume state: {0}'.format(vol.volume_state()))
                crypt = 'crypt-{0}'.format(device.split('/')[-1])
                self.ssh.sudo('pwgen -y 256 1 | cryptsetup create {crypt} '
                              '{device}'.format(crypt=crypt, device=device))
                self.ssh.sudo('cryptsetup status {0}'.format(crypt))
                device = '/dev/mapper/{0}'.format(crypt)
            self.ssh.sudo('mkfs.{0} {1}'.format(self.fs_type, device))
            self.ssh.sudo('mkdir {0}'.format(mount_point))
            self.ssh.sudo('mount {0} {1}'.format(device, mount_point))
        except:
            self._destroy_volume(vol)
            raise
        return vol

    def _destroy_volume(self, vol):
        """
        Forcibly detaches and destroys the given EBS volume, where vol is an
        instance of ``boto.ec2.volume``.
        """
        logger.debug('Detaching volume {0}'.format(vol.id))
        vol.detach(force=True)
        logger.debug('Waiting for volume {0} to become '
                     'available'.format(vol.id))
        while vol.volume_state() == 'in-use':
            time.sleep(1)
            vol.update()
        logger.debug('Deleting volume {0}'.format(vol.id))
        vol.delete()

    def setup(self):
        """
        Extends the base EC2Instance ``setup()`` method with routines to
        run apt-get update and, if desired, apt-get upgrade, on the instance.
        Also creates volumes defined in the ``volume_info`` list on this
        instance.
        """
        super(UbuntuInstance, self).setup()
        self.ssh.sudo('apt-get update')
        if self.run_upgrade:
            self.ssh.sudo('apt-get upgrade -y')
        for vol in self.volume_info:
            self.volumes.append(self._create_volume(*vol))

    def cleanup(self):
        """
        Destroys any volumes created for this instance and then calls the
        base class's ``cleanup()`` method.
        """
        while self.volumes:
            vol = self.volumes.pop()
            self._destroy_volume(vol)
        super(UbuntuInstance, self).cleanup()


class MicroLucidInstance(UbuntuInstance):
    """
    Sample Micro instance running Ubuntu Lucid on an EBS root filesystem.
    """
    ami = 'ami-3e02f257' # Lucid EBS
    instance_type = 't1.micro'
    key_prefix = 'micro-ubuntu-'


class SmallLucidInstance(UbuntuInstance):
    """
    Sample Small instance running Ubuntu Lucid on on an instance-store root
    filesystem.
    """
    ami = 'ami-7000f019' # Lucid instance store
    instance_type = 'm1.small'
    key_prefix = 'small-ubuntu-'

