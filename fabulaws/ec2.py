import os
import uuid
import time
import socket
import tempfile
import logging
import string
from random import choice
from StringIO import StringIO

import traceback
import paramiko
from boto.ec2.connection import EC2Connection
from boto.ec2 import elb
from boto.exception import BotoServerError
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
        logger.debug('Connecting to EC2')
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
            # XXX find the proper way to default to the default Fabric user
            self.user = os.environ['USER']
            self._placement = instance.placement
        elif instance_id:
            self.conn = self._connect_ec2()
            # attach to an existing instance
            self.attach_to(instance_id)
            self._placement = instance.placement
        else:
            self.conn = self._connect_ec2()
        self.elb_conn = self._connect_elb()

    def _connect_ec2(self):
        logger.debug('Connecting to EC2')
        return EC2Connection(self._key_id, self._secret)

    def _connect_elb(self):
        logger.debug('Connecting to ELB')
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

    def _create_instances(self, instance_id=None, count=1, ami=None, placement=None, wait_ssh=True):
        """
        Creates a new EC2 instance.  The instance is destroyed when exiting the
        context manager or destroying this object.
        """
        if ami is None:
            ami = self.ami
        if placement is None:
            placement = self._placement
        if instance_id:
            logger.info('Fetching existing instance {0}'.format(instance_id))
            res = self.conn.get_all_instances([instance_id])[0]
            created = False
        else:
            logger.info('Creating EC2 instances')
            image = self.conn.get_image(ami)
            key_name = self.key and self.key.name or None
            res = image.run(key_name=key_name,
                            security_groups=self.security_groups,
                            instance_type=self.instance_type,
                            placement=placement,
                            min_count=count, max_count=count)
            time.sleep(5) # wait for AWS to catch up
            created = True
        for inst in res.instances:
            if self._tags:
                logger.debug('Creating tags on instance.')
                
                self.conn.create_tags([inst.id], self._tags)
            logger.debug('Attached to EC2 instance {0}'.format(inst.id))
        for inst in res.instances:
            if created:
                try:
                    logger.info('Waiting for instance to enter "running" state...')
                    while inst.update() != 'running':
                        time.sleep(2)
                    if wait_ssh:
                        logger.info('Waiting for SSH daemon to launch...')
                        self._wait_for_ssh(inst)
                except:
                    logger.info('Terminating instance early due to unexpected '
                                'error')
                    inst.terminate()
                    raise
        return res.instances

    def _wait_for_ssh(self, instance):
        """
        Keeps retrying an SSH connection until it succeeds, then closes the
        connection and returns.
        """
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
        times = 0
        wait = 2
        while times < 120/wait:
            try:
                key = self.key_file and self.key_file.name or env.key_filename
                user = self.user and self.user or env.user
                ssh.connect(instance.public_dns_name, allow_agent=False,
                            look_for_keys=False, username=user,
                            key_filename=key, timeout=self.ssh_timeout)
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
        else:
            env.key_filename = None
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

    @property
    def region(self):
        if self._placement:
            return self._placement[:-1]

    @property
    def tags(self):
        if self._tags is None:
            tgs = self.conn.get_all_tags({'resource-id': self.instance.id})
            self._tags = dict([(t.name, t.value) for t in tgs])
        return self._tags

    def reset_authentication(self):
        """
        Resets this instance to use the default Fabric user, rather than
        the default sysadmin user on this AMI.  This can be called, e.g., after
        creating personal sysadmin users on the remote server so that SSH
        agent forwarding will work properly when connecting to other remote
        servers.
        """
        if len(self._saved_contexts) > 0:
            raise ValueError('reset_authentication() can only be called when '
                             'a FabulAWS context is inactive.')
        self.user = env.user
        self.key_filename = None

    def attach_to(self, instance_id):
        """
        Attaches to an existing EC2 instance, identified by instance_id.
        """
        self.instance = self._create_instances(instance_id=instance_id)[0]

    def setup(self):
        """
        Creates the instance and sets up the Fabric context.  Extend this
        method in your subclass to further customize the instance.
        """
        self.key, self.key_file = self._create_key_pair()
        self.instance = self._create_instances()[0]

    def add_to_elb(self, elb_name):
        """
        Adds this instance to the specified load balancer.
        """
        # ensure that the load balancer accepts traffic to this AV
        self.elb_conn.enable_availability_zones(elb_name, [self._placement])
        return self.elb_conn.register_instances(elb_name, [self.instance.id])

    def remove_from_elb(self, elb_name):
        """
        Removes this instance from the specified load balancer.
        """
        return self.elb_conn.deregister_instances(elb_name, [self.instance.id])

    def elb_state(self, elb_name):
        """
        Returns the InstanceState for this instance in the specified load balancer.
        """
        try:
            return self.elb_conn.describe_instance_health(elb_name, [self.instance.id])[0].state
        except BotoServerError:
            logger.exception('Failed to get instance health, assuming OutOfService')
            return 'OutOfService'

    def wait_for_elb_state(self, elb_name, state, max_wait=300):
        """
        Waits for this instance to enter the given state in the given load balancer.
        """
        curr_state = self.elb_state(elb_name)
        waited = 0
        wait = 5
        while curr_state != state:
            if waited > max_wait:
                raise Exception('Instance {inst} did not enter {state} state in '
                                ' LB {elb} after waiting {secs} seconds'
                                ''.format(inst=self.instance.id, state=state,
                                          elb=elb_name, secs=max_wait))
            time.sleep(wait)
            waited += wait
            curr_state = self.elb_state(elb_name)
        return curr_state

    def reboot(self):
        """Reboots this server."""
        self.conn.reboot_instances([self.instance.id])

    def _image_name(self):
        if 'Name' in self.tags:
            return self.tags['Name']
        else:
            return 'Image of {0}'.format(self.instance.id)

    def create_image(self, replace_existing=False, name=None):
        """
        Creates an AMI of this instance.
        """
        if not name:
            name = self._image_name()
        if replace_existing:
            images = self.conn.get_all_images(filters={'tag:Name': name})
            if images:
                logger.info('Deleting images {0}'.format(images))
                [img.deregister() for img in images]
        image_id = self.conn.create_image(self.instance.id, name)
        time.sleep(1) # wait for AWS to catch up
        image = self.conn.get_image(image_id)
        self.conn.create_tags([image_id], self.tags)
        logger.info('Waiting for image to enter "available" state...')
        while image.update() == 'pending':
            time.sleep(2)
        assert image.update() == 'available'
        logger.info('Image creation finished.')
        return image

    def create_copies(self, count, placement=None, recreate_image=True, **kwargs):
        """
        Creates ``count`` copies of this instance by creating an AMI and then
        running that.
        """
        if recreate_image:
            image = self.create_image(replace_existing=True)
        else:
            name = self._image_name()
            image = self.conn.get_all_images(filters={'tag:Name': name})[0]
        instances = self._create_instances(count=count, ami=image.id,
                                           placement=placement, wait_ssh=False)
        return [EC2Instance(instance=inst, **kwargs) for inst in instances]

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
        self.conn.create_tags([self.instance.id], tags)

    @property
    def hostname(self):
        if self.instance:
            return self.instance.public_dns_name
        else:
            raise ValueError('No instance has been created yet, or the '
                             'instance has already been destroyed.')

    @property
    def internal_ip(self):
        if self.instance:
            return self.instance.private_ip_address
        else:
            raise ValueError('No instance has been created yet, or the '
                             'instance has already been destroyed.')

    def __enter__(self):
        self._setup_context()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._restore_context()

    def __del__(self):
        # If the interpretter is exciting, all variables and modules in this
        # class will be set to None, so don't bother trying to clean up after
        # ourselves (it won't work).
        if EC2Instance:
            self.cleanup()
