import os
import uuid
import time
import socket
import tempfile
import logging
import string
from random import choice
from StringIO import StringIO

import paramiko
from boto.ec2.connection import EC2Connection
from boto.ec2 import elb
from fabric.api import *
from fabric.contrib import files
from fabulaws.api import *

logger = logging.getLogger('fabulaws.ec2')


class EC2Service(object):
    """
    Represents a connection to the EC2 service
    """

    def __init__(self, access_key_id=None, secret_access_key=None):
        # ensure these attributes exist
        self.conn = None
        self._key_id = access_key_id or os.environ['AWS_ACCESS_KEY_ID']
        self._secret = secret_access_key or os.environ['AWS_SECRET_ACCESS_KEY']
        self.setup()

    def _connect_ec2(self):
        logger.info('Connecting to EC2')
        return EC2Connection(self._key_id, self._secret)

    def setup(self):
        self.conn = self._connect_ec2()

    def instances(self, filters=None, cls=None, inst_kwargs=None):
        """
        Return list of all matching reservation instances
        """
        filters = filters or {}
        if 'instance-state-name' not in filters:
            filters['instance-state-name'] = 'running'
        cls = cls or EC2Instance
        inst_kwargs = inst_kwargs or {}
        reservations = self.conn.get_all_instances(filters=filters)
        results = []
        for reservation in reservations:
            for instance in reservation.instances:
                results.append(cls(instance=instance, **inst_kwargs))
        return results

    def public_dns(self, filters=None, cls=None, inst_kwargs=None):
        """
        List all public DNS entries for all running instances
        """
        instances = self.instances(filters, cls, inst_kwargs)
        return [i.hostname for i in instances]


class EC2Instance(object):
    """
    Base class for EC2 instances.
    """
    ami = ''
    user = ''
    admin_groups = []
    instance_type = ''
    security_groups = []
    key_prefix = ''
    ssh_timeout = 5

    _saved_contexts = []

    def __init__(self, access_key_id=None, secret_access_key=None,
                 terminate=False, placement=None, tags=None, instance_id=None,
                 instance=None):
        if (not self.ami or not self.user or not self.instance_type) and \
          not instance_id and not instance:
            raise Exception('You must extend this class and define the ami, '
                            'user, and instance_type class variables.')
        # ensure these attributes exist
        self.conn = self.elb_conn = None
        self.key = self.key_file = self.instance = None
        self._terminate = terminate
        self._placement = placement
        self._tags = tags
        if terminate or tags or placement:
            logger.warning('The terminate, tags, and placement arguments '
                           'have no effect when instance_id is set.')
        self._key_id = access_key_id or os.environ['AWS_ACCESS_KEY_ID']
        self._secret = secret_access_key or os.environ['AWS_SECRET_ACCESS_KEY']
        if instance:
            self.conn = instance.connection
            self.instance = instance
            self.user = None
        elif instance_id:
            self.conn = self._connect_ec2()
            # attach to an existing instance
            self.attach_to(instance_id)
        else:
            self.conn = self._connect_ec2()
            # setup a new instance
            self.setup()
        self.elb_conn = self._connect_elb()

    def _connect_ec2(self):
        logger.info('Connecting to EC2')
        return EC2Connection(self._key_id, self._secret)

    def _connect_elb(self):
        logger.info('Connecting to ELB')
        return elb.ELBConnection(self._key_id, self._secret)

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

    def _create_instance(self, instance_id=None):
        """
        Creates a new EC2 instance.  The instance is destroyed when exiting the
        context manager or destroying this object.
        """
        if instance_id:
            logger.info('Fetching existing instance {0}'.format(instance_id))
            res = self.conn.get_all_instances([instance_id])[0]
            created = False
        else:
            logger.info('Creating EC2 instance')
            image = self.conn.get_image(self.ami)
            res = image.run(key_name=self.key.name,
                            security_groups=self.security_groups,
                            instance_type=self.instance_type,
                            placement=self._placement)
            created = True
        inst = res.instances[0]
        logger.debug('Attached to EC2 instance {0}'.format(inst.id))
        if created:
            try:
                logger.info('Waiting for instance to enter "running" state...')
                time.sleep(5) 
                while inst.update() != 'running':
                    time.sleep(2)
                logger.info('Waiting for SSH daemon to launch...')
                self._wait_for_ssh(inst)
            except:
                logger.info('Terminating instance early due to unexpected '
                            'error')
                inst.terminate()
                raise
        return inst

    def _wait_for_ssh(self, instance):
        """
        Keeps retrying an SSH connection until it succeeds, then closes the
        connection and returns.
        """
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        times = 0
        wait = 2
        while times < 120/wait:
            try:
                ssh.connect(instance.public_dns_name, allow_agent=False,
                            look_for_keys=False, username=self.user,
                            key_filename=self.key_file.name,
                            timeout=self.ssh_timeout)
                break
            except (EOFError, socket.error, paramiko.SSHException), e:
                logger.debug('Error connecting ({0}); retrying in {1} '
                             'seconds'.format(e, wait))
                times += 1
                time.sleep(wait)
        ssh.close()

    def _setup_context(self):
        """
        Sets up the Fabric context so commands can be run on this instance.
        """
        logger.info('Setting up context')
        context = {}
        for attr in 'key_filename', 'user', 'host_string':
            context[attr] = getattr(env, attr)
        self._saved_contexts.append(context)
        if self.key_file:
            logger.debug('Setting env.key_filename = "{0}"'
                         ''.format(self.key_file.name))
            env.key_filename = [self.key_file.name]
        if self.user:
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
        context = self._saved_contexts.pop()
        for key, value in context.items():
            setattr(env, key, value)

    def attach_to(self, instance_id):
        """
        Attaches to an existing EC2 instance, identified by instance_id.
        """
        self.instance = self._create_instance(instance_id=instance_id)

    def setup(self):
        """
        Creates the instance and sets up the Fabric context.  Extend this
        method in your subclass to further customize the instance.
        """
        self.key, self.key_file = self._create_key_pair()
        self.instance = self._create_instance()
        self.add_tags(self._tags)

    def add_to_elb(self, elb_name):
        """
        Adds this instance to the specified load balancer.
        """
        return self.elb_conn.register_instances(elb_name, [self.instance.id])

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
        if self.instance and self._terminate:
            logger.debug('Terminating instance {0}'.format(self.instance.id))
            self.instance.terminate()
            self.instance = None
        elif self.instance:
            logger.warning('Left instance "{0}" running at {1}'
                           ''.format(self.instance.id, self.hostname))
        if self.key_file:
            logger.debug('Deleting key file {0}'.format(self.key_file.name))
            self.key_file.close()
            self.key_file = None

    def add_tags(self, tags):
        """
        Associate specified tags with instance
        """
        if tags:
            self.conn.create_tags([self.instance.id], tags)

    @property
    def hostname(self):
        if self.instance:
            return self.instance.public_dns_name
        else:
            raise ValueError('No instance has been created yet, or the '
                             'instance has already been destroyed.')

    def __enter__(self):
        self._setup_context()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._restore_context()

    def __del__(self):
        self.cleanup()


class UbuntuInstance(EC2Instance):
    """
    Base class for all Ubuntu instances.
    """
    user = 'ubuntu'
    admin_groups = ['admin']
    volume_info = [] # tuples of (device, mount_point, size_in_GB)
    fs_type = 'ext3'
    fs_encrypt = True
    run_upgrade = True
    
    def __init__(self, *args, **kwargs):
        self.volumes = []
        super(UbuntuInstance, self).__init__(*args, **kwargs)

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
            with self:
                if self.fs_encrypt:
                    sudo('apt-get install -y cryptsetup')
                    crypt = 'crypt-{0}'.format(device.split('/')[-1])
                    sudo('cryptsetup -y luksFormat {device}'.format(device=device))
                    sudo('cryptsetup luksOpen {device} {crypt}'.format(device=device, crypt=crypt))
                    device = '/dev/mapper/{0}'.format(crypt)
                sudo('mkfs.{0} {1}'.format(self.fs_type, device))
                sudo('mkdir {0}'.format(mount_point))
                sudo('mount {0} {1}'.format(device, mount_point))
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
        with self:
            sudo('apt-get update')
            if self.run_upgrade:
                sudo('apt-get upgrade -y')
        for vol in self.volume_info:
            self.volumes.append(self._create_volume(*vol))

    def create_users(self, users, ignore_existing=True):
        """
        Create admin users and deploy SSH keys to the server.  ``users`` is
        a list of (username, keyfile) tuples.  The users will be created with
        empty passwords.
        """
        if self.admin_groups:
            groups = '-G {0}'.format(','.join(self.admin_groups))
        else:
            groups = ''
        with self:
            for name, keyfile in users:
                if ignore_existing and files.exists('/home/{0}'.format(name)):
                    logger.info('Not creating existing user {0}'.format(name))
                    continue
                sudo('useradd -m {0} -s /bin/bash {1}'.format(groups, name))
                sudo('passwd -d {0}'.format(name))
                sudo('mkdir /home/{0}/.ssh'.format(name))
                put(keyfile, '/home/{0}/.ssh/authorized_keys'.format(name),
                    use_sudo=True)
                sudo('chown -R {0} /home/{0}/.ssh'.format(name))

    def secure_directories(self, secure_dirs, secure_root):
        """
        Move the given directories, ``secure_dirs'', to the secure file system
        mounted at ``secure_root''.
        """
        with self:
            assert files.exists(secure_root)
            for sdir in secure_dirs:
                secured_sdir = ''.join([secure_root, sdir])
                secured_parent = call_python('os.path.dirname', secured_sdir)
                if files.exists(sdir):
                    sudo('mkdir -p {0}'.format(secured_parent))
                    sudo('mv {0} {1}'.format(sdir, secured_sdir))
                else:
                    sudo('mkdir -p {0}'.format(secured_sdir))
                sudo('mkdir -p {0}'.format(sdir))
                sudo('mount -o bind {0} {1}'.format(secured_sdir, sdir))

    def cleanup(self):
        """
        If needed, destroys any volumes created for this instance and then
        calls the base class's ``cleanup()`` method.
        """
        if self._terminate:
            while self.volumes:
                vol = self.volumes.pop()
                self._destroy_volume(vol)
        else:
            for vol in self.volumes:
                logger.warning('Left volume "{0}" in state "{1}"'
                               ''.format(vol.id, vol.volume_state()))
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

