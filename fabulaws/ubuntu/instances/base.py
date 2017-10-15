import os
import time
import copy
import logging

import boto.exception

from decimal import Decimal

from fabric.api import *
from fabric.contrib import files

from fabulaws.api import *
from fabulaws.decorators import uses_fabric
from fabulaws.ec2 import EC2Instance
from fabulaws.ubuntu.packages.base import BaseAptMixin

__all__ = ['UbuntuInstance']

logger = logging.getLogger('fabulaws.ubuntu.instances.base')

class UbuntuInstance(BaseAptMixin, EC2Instance):
    """
    Base class for all Ubuntu instances.
    """
    user = 'ubuntu'
    admin_groups = ['admin']
    volume_info = [] # tuples of (device, mount_point, size_in_GB, type, passwd)
    fs_type = 'ext3'
    fs_encrypt = False
    ubuntu_mirror = None
    mount_script = '/mount-deferred.sh'

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
    def _encrypt_device(self, device, passwd=None):
        """
        Encrypts the given device.  If a password is not specified,
        a prompt will be issued.
        """
        if not passwd:
            passwd = getpass.getpass('Enter LUKS passphrase for cryptsetup: ')
        self.install_packages(['python-pexpect', 'cryptsetup'])
        crypt = 'crypt-{0}'.format(device.split('/')[-1])
        with hide('stdout'):
            answers = [
                (r'Are you sure\? \(Type uppercase yes\):', 'YES'),
                ('Enter .*passphrase:', passwd),
                ('Verify passphrase:', passwd),
            ]
            answer_sudo('cryptsetup -y luksFormat {device}'.format(device=device),
                        answers=answers)
            answers = [('Enter passphrase for .+:', passwd)]
            answer_sudo('cryptsetup luksOpen {device} {crypt}'
                        ''.format(device=device, crypt=crypt),
                        answers=answers)
        device = '/dev/mapper/{0}'.format(crypt)
        return device

    @uses_fabric
    def _mount_and_persist(self, device, mount_point, fs_type=None, opts=None):
        mount_cmd = ' '.join([
            'mount',
            '-o {}'.format(opts) if opts else '',
            '-t {}'.format(fs_type) if fs_type else '',
            device,
            mount_point,
        ])
        fstab_entry = ' '.join([
            device,
            mount_point,
            fs_type if fs_type else self.fs_type,
            opts if opts else 'defaults',
            '0',
            '0',
        ])
        sudo(mount_cmd)
        if self.fs_encrypt:
            if not files.exists(self.mount_script):
                files.append(self.mount_script, "#!/bin/sh", use_sudo=True)
                sudo('chmod a+x {}'.format(self.mount_script))
            files.append(self.mount_script, mount_cmd, use_sudo=True)
        else:
            files.append('/etc/fstab', fstab_entry, use_sudo=True)

    @uses_fabric
    def _format_volume(self, device, mount_point, passwd=None):
        """
        Creates an EBS volume of size ``vol_size``, manifests the device at
        ``device`` in this instance, and mounts it at ``mount_point``.
        """
        logger.info('Formatting {0}'.format(device))
        if self.fs_encrypt:
            device = self._encrypt_device(device, passwd)
        sudo('mkfs.{0} {1}'.format(self.fs_type, device))
        sudo('mkdir {0}'.format(mount_point))
        self._mount_and_persist(device, mount_point)

    def _set_volume_tags(self, vol, device, tags=None):
        if tags is None:
            tags = copy.copy(self._tags) or {}
        if 'Name' in tags:
            tags['Name'] = '_'.join([tags['Name'], os.path.basename(device)])
        else:
            tags['Name'] = '_'.join([inst.id, os.path.basename(device)])
        tags['device'] = device
        self.conn.create_tags([vol.id], tags)

    def add_tags(self, tags):
        """
        Propagate any tag updates on the instance to the associated volumes
        (e.g., for name changes).
        """
        super(UbuntuInstance, self).add_tags(tags)
        # allow super class to update self._tags and use that in _set_volume_tags
        for vol, (device, _, _, _, _)  in zip(self.volumes, self.volume_info):
            self._set_volume_tags(vol, device)

    @uses_fabric
    def _create_volume(self, device, mount_point, vol_size, vol_type, passwd=None):
        """
        Creates an EBS volume of size ``vol_size``, manifests the device at
        ``device`` in this instance, and mounts it at ``mount_point``.
        """
        logger.info('Attaching {0}'.format(device))
        inst = self.instance
        # the placement is the availability zone
        vol = self.conn.create_volume(vol_size, inst.placement, volume_type=vol_type)
        self._set_volume_tags(vol, device)
        try:
            logger.debug('Waiting for volume {0} to become AVAILABLE '
                         '(current state={1})'.format(vol.id, vol.volume_state()))
            while vol.volume_state() != 'available':
                time.sleep(1)
                vol.update()
                logger.debug('  current state: {0}'.format(vol.volume_state()))
            vol.attach(inst.id, device)
            logger.debug('Waiting for volume {0} to become ATTACHED '
                         '(current state={1})'.format(vol.id, vol.volume_state()))
            while vol.volume_state() != 'in-use':
                time.sleep(1)
                vol.update()
                logger.debug('  current state: {0}'.format(vol.volume_state()))
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
        try:
            vol.detach(force=True)
        except boto.exception.EC2ResponseError:
            logger.exception('Failed to detach volume; continuing anyway.')
        logger.debug('Waiting for volume {0} to become '
                     'available'.format(vol.id))
        while vol.volume_state() == 'in-use':
            time.sleep(1)
            vol.update()
        logger.debug('Deleting volume {0}'.format(vol.id))
        vol.delete()

    @property
    @uses_fabric
    def server_memory(self):
        """Returns total server memory, in MB"""
        if not hasattr(self, '_server_memory'):
            mem = run('cat /proc/meminfo|grep MemTotal')
            self._server_memory = int(mem.split()[1]) / 1024
        return self._server_memory

    @property
    @uses_fabric
    def ubuntu_release(self):
        if not hasattr(self, '_ubuntu_release'):
            self._ubuntu_release = Decimal(run('lsb_release -r -s').strip())
        return self._ubuntu_release

    @uses_fabric
    def setup_mirror(self, mirror=None):
        if not mirror:
            mirror = self.ubuntu_mirror
        if mirror:
            orig = '{region}.ec2.archive.ubuntu.com'.format(region=self.region)
            mirror = mirror.format(region=self.region)
            files.sed('/etc/apt/sources.list', orig, mirror, use_sudo=True)

    def setup(self):
        """
        Extends the base EC2Instance ``setup()`` method with routines to
        update apt sources on the instance.  Also creates volumes defined in
        the ``volume_info`` list on this instance.
        """
        super(UbuntuInstance, self).setup()
        # this is required because we may need to install cryptsetup when
        # creating volumes
        self.setup_mirror()
        self.update_apt_sources()
        # the first apt-get update may update sources.list, so re-run it here
        self.setup_mirror()
        self.update_apt_sources()
        for vol in self.volume_info:
            if len(vol) == 5:
                device, mount_point, vol_size, vol_type, passwd = vol
            else:
                raise Exception('volume_info must be populated with tuples of '
                                '(device, mount_point, vol_size, vol_type, passwd)')
            if device == 'instance-store':
                with self:
                    device = run("mount|grep /mnt|cut -d' ' -f1").strip()
                    sudo('umount {0}'.format(device))
            else:
                self.volumes.append(self._create_volume(device, mount_point,
                                                        vol_size, vol_type, passwd))
            device = self._wait_for_device(device)
            self._format_volume(device, mount_point, passwd)

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
            else:
                sudo('useradd -m {0} -s /bin/bash {1}'.format(groups, name))
                sudo('passwd -d {0}'.format(name))
                sudo('mkdir /home/{0}/.ssh'.format(name))
            put(keyfile, '/home/{0}/.ssh/authorized_keys2'.format(name),
                use_sudo=True, mode=0600)
            sudo('chown -R {0} /home/{0}/.ssh'.format(name))
            # if a file exists with the comment field (e.g., for GECOS info)
            # for the user, use usermod -c to add it.
            gecos_file = keyfile + '.gecos'
            if os.path.exists(gecos_file):
                with open(gecos_file, 'r') as gecos_fd:
                    gecos = gecos_fd.readline().strip()
                    sudo('usermod -c "{}" {}'.format(gecos, name))

    @uses_fabric
    def bind_app_directories(self, app_dirs, app_root):
        """
        Move the given directories, ``app_dirs'', to the specified file system
        mounted at ``app_root'' (optionally secure if ``self.fs_encrypt == True'').
        """
        assert files.exists(app_root)
        for app_dir in app_dirs:
            bound_app_dir = ''.join([app_root, app_dir])
            bound_parent_dir = call_python('os.path.dirname', bound_app_dir)
            if files.exists(app_dir):
                sudo('mkdir -p {0}'.format(bound_parent_dir))
                sudo('mv {0} {1}'.format(app_dir, bound_app_dir))
            else:
                sudo('mkdir -p {0}'.format(bound_app_dir))
            sudo('mkdir -p {0}'.format(app_dir))
            self._mount_and_persist(bound_app_dir, app_dir, fs_type='none', opts='bind')

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
