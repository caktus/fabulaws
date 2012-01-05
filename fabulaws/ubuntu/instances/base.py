import time
import logging

from fabric.api import *
from fabric.contrib import files

from fabulaws.api import *
from fabulaws.decorators import uses_fabric
from fabulaws.ec2 import EC2Instance
from fabulaws.ubuntu.packages.apt import AptMixin

__all__ = ['UbuntuInstance']

logger = logging.getLogger('fabulaws.ubuntu.instances.base')

class UbuntuInstance(AptMixin, EC2Instance):
    """
    Base class for all Ubuntu instances.
    """
    user = 'ubuntu'
    admin_groups = ['admin']
    volume_info = [] # tuples of (device, mount_point, size_in_GB)
    fs_type = 'ext3'
    fs_encrypt = True

    def __init__(self, *args, **kwargs):
        self.volumes = []
        super(UbuntuInstance, self).__init__(*args, **kwargs)

    @uses_fabric
    def _wait_for_device(self, device, max_tries=30):
        """
        Waits for the given device to manifest in /dev, and returns the actual
        path of the device.
        """
        # try all possible paths for the device in turn until one shows up
        devices = [device, device.replace('/dev/sd', '/dev/xvd')]
        logger.info('Waiting for device {0} to appear'.format(device))
        for _ in range(max_tries):
            for device in devices:
                if files.exists(device):
                    logger.debug('Found device {0}'.format(device))
                    return device
            time.sleep(1)

    @uses_fabric
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
            while vol.volume_state() != 'in-use':
                time.sleep(1)
                vol.update()
            device = self._wait_for_device(device)
            if self.fs_encrypt:
                self.install_packages(['cryptsetup'])
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
        update apt sources on the instance.  Also creates volumes defined in
        the ``volume_info`` list on this instance.
        """
        super(UbuntuInstance, self).setup()
        # this is required because we may need to install cryptsetup when
        # creating volumes
        self.update_apt_sources()
        # the first apt-get update may update sources.list, so re-run it here
        self.update_apt_sources()
        for vol in self.volume_info:
            self.volumes.append(self._create_volume(*vol))

    @uses_fabric
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
        for name, keyfile in users:
            if ignore_existing and files.exists('/home/{0}'.format(name)):
                logger.info('Not creating existing user {0}'.format(name))
                continue
            sudo('useradd -m {0} -s /bin/bash {1}'.format(groups, name))
            sudo('passwd -d {0}'.format(name))
            sudo('mkdir /home/{0}/.ssh'.format(name))
            put(keyfile, '/home/{0}/.ssh/authorized_keys2'.format(name),
                use_sudo=True, mode=0600)
            sudo('chown -R {0} /home/{0}/.ssh'.format(name))

    @uses_fabric
    def secure_directories(self, secure_dirs, secure_root):
        """
        Move the given directories, ``secure_dirs'', to the secure file system
        mounted at ``secure_root''.
        """
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
