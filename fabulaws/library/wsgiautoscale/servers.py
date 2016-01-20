from __future__ import with_statement

import os
import time
import subprocess

from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import uses_fabric
from fabulaws.ec2 import EC2Instance
from fabulaws.ubuntu.instances import UbuntuInstance
from fabulaws.ubuntu.packages.fail2ban import Fail2banMixin
from fabulaws.ubuntu.packages.postgres import PostgresMixin
from fabulaws.ubuntu.packages.redis import RedisPpaMixin
from fabulaws.ubuntu.packages.memcached import MemcachedMixin
from fabulaws.ubuntu.packages.python import PythonMixin
from fabulaws.ubuntu.packages.rabbitmq import RabbitMqMixin


__all__ = [
    'CacheInstance',
    'DbMasterInstance',
    'DbSlaveInstance',
    'WorkerInstance',
    'WebInstance',
    'CombinedInstance',
]


class FirewallMixin(Fail2banMixin):
    pass


class BaseInstance(FirewallMixin, UbuntuInstance):
    deployment_dir = os.path.dirname(__file__)
    project_root = os.path.dirname(deployment_dir)

    def __init__(self, *args, **kwargs):
        for key in ['ami', 'key_prefix', 'admin_groups', 'run_upgrade',
                    'secure_root', 'secure_home', 'fs_type', 'fs_encrypt',
                    'ubuntu_mirror', 'swap_multiplier', 'instance_type',
                    'deploy_user', 'volume_size', 'volume_type',
                    'security_groups', 'home']:
            setattr(self, key, kwargs.pop(key))
        if 'terminate' not in kwargs:
            kwargs['terminate'] = False
        passwd = getattr(env, 'luks_passphrase', None)
        self.volume_info = [('/dev/sdf', self.secure_root, self.volume_size,
                             self.volume_type, passwd)]
        if self.secure_root:
            self.default_swap_file = '%s/swapfile' % self.secure_root
        else:
            self.default_swap_file = '/swapfile'
        super(BaseInstance, self).__init__(*args, **kwargs)
        if self.fs_encrypt:
            self.secure_dirs = ['/tmp', self.secure_home] # mixins add other dirs

    def _get_users(self):
        """
        Returns a list of tuples of (username, key_file_path).
        """
        users_dir = env.ssh_keys
        users = [(n, os.path.join(users_dir, n))
                 for n in os.listdir(users_dir)]
        return users

    def _add_swap(self, path):
        sudo('mkswap -f {0}'.format(path))
        sudo('swapon {0}'.format(path))
        files.append('/etc/fstab', '{0} swap swap defaults 0 0'.format(path), use_sudo=True)

    @uses_fabric
    def setup_swap(self):
        """Sets up swap partition"""
        swap_mb = self.server_memory * self.swap_multiplier
        devs = ['/dev/xvdb', '/dev/xvdc']
        for dev in devs:
            print 'attempting swap creation on {0}...'.format(dev)
            if swap_mb <= 0:
                print 'no additional swap needed; skipping'
                break
            if not files.exists(dev):
                print 'no such device {0}; skipping'.format(dev)
                continue
            size = sudo('blockdev --getsize64 {0}'.format(dev))
            try:
                size = int(size) / 1024 / 1024
            except ValueError:
                print 'no size found for {0}'.format(dev)
                continue
            # decrement size regardless of whether or not we create swap; if
            # crypt device exists, assume we created it previously and don't 
            # create even more swap
            swap_mb -= size
            with settings(warn_only=True):
                sudo('umount {0}'.format(dev))
            crypt_name = 'cryptswap-{0}'.format(dev.split('/')[-1])
            if files.exists('/dev/mapper/{0}'.format(crypt_name)):
                print 'crypt device {0} already exists; skipping'.format(crypt_name)
                continue
            sudo('cryptsetup -d /dev/urandom create {0} {1}'.format(crypt_name, dev))
            files.append('/etc/crypttab',
                         'cryptswap {0} /dev/urandom swap'.format(dev), use_sudo=True)
            files.comment('/etc/fstab', dev, use_sudo=True)
            self._add_swap('/dev/mapper/{0}'.format(crypt_name))
        if swap_mb > 0:
            if not files.exists(self.default_swap_file):
                sudo('dd if=/dev/zero of={0} bs=1M count={1}'.format(self.default_swap_file, swap_mb))
                sudo('chown root:root {0}'.format(self.default_swap_file))
                sudo('chmod 600 {0}'.format(self.default_swap_file))
                self._add_swap(self.default_swap_file)
            else:
                print 'swap file {0} already exists; skipping'.format(self.default_swap_file)
        # remove old swap at the end in case it's already in use (otherwise swapoff might fail)
        old_swap = ['/dev/xvda3']
        for swap in old_swap:
            if files.contains('/proc/swaps', swap):
                sudo('swapoff {0}'.format(swap))
                files.comment('/etc/fstab', swap, use_sudo=True)
                with settings(warn_only=True):
                    sudo('dd if=/dev/zero of={0} bs=1M'.format(swap))

    @uses_fabric
    def setup_sudoers(self):
        """
        Creates the sudoers file on the server, based on the supplied template.
        """
        sudoers_file = os.path.join(self.deployment_dir, 'templates', 'sudoers')
        files.upload_template(sudoers_file, '/etc/sudoers.new', backup=False,
                              use_sudo=True, mode=0440)
        sudo('chown root:root /etc/sudoers.new')
        sudo('mv /etc/sudoers.new /etc/sudoers')

    @uses_fabric
    def create_deployer(self):
        """
        Creates a deployment user with a directory for Apache configurations.
        """
        user = self.deploy_user
        sudo('useradd -d {0} -m -s /bin/bash {1}'.format(self.home, user))
        sudo('mkdir {0}/.ssh'.format(self.home), user=user)

    @uses_fabric
    def update_deployer_keys(self):
        """
        Replaces deployer keys with the current sysadmin users keys.
        """
        user = self.deploy_user
        file_ = '{0}/.ssh/authorized_keys2'.format(self.home)
        if files.exists(file_):
            sudo('rm {0}'.format(file_), user=user)
        sudo('touch {0}'.format(file_), user=user)
        for _, key_file in self._get_users():
            files.append(file_, open(key_file).read().strip(), use_sudo=True)

    @property
    @uses_fabric
    def server_memory(self):
        """Returns total server memory, in MB"""
        total = run('cat /proc/meminfo|grep MemTotal')
        while '  ' in total:
            total = total.replace('  ', ' ')
        total = int(total.split(' ')[1])
        return total/1024

    def setup(self):
        """
        Creates sysadmin users and secures the required directories.
        """
        super(BaseInstance, self).setup()
        self.instance.modify_attribute('blockDeviceMapping', ['%s=true' % v[0] for v in self.volume_info] )
        self.create_users(self._get_users())
        self.setup_sudoers()
        # needed for SSH agent forwarding during replication setup:
        self.reset_authentication()
        if self.fs_encrypt:
            self.secure_directories(self.secure_dirs, self.secure_root)
        self.setup_swap() # after secure partition is created
        self.create_deployer()
        self.update_deployer_keys()
        self.upgrade_packages()
        self.install_packages(['ntp']) # keep date current


class SessionMixin(RedisPpaMixin):
    """Mixin that creates a session store using Redis."""

    redis_bind = '' # allow connections on all interfaces

    def __init__(self, *args, **kwargs):
        super(SessionMixin, self).__init__(*args, **kwargs)
        if self.fs_encrypt:
            self.secure_dirs.append('/var/lib/redis')


class CacheMixin(MemcachedMixin):
    """Mixin that creates a cache using Memcached."""

    memcached_bind = '' # allow connections on all interfaces
    memcached_connections = 10000
    memcached_ulimit = 20000
    memcached_threads = 5

    def __init__(self, *args, **kwargs):
        super(CacheMixin, self).__init__(*args, **kwargs)

    @property
    @uses_fabric
    def memcached_memory(self):
        """Returns half of total server memory, in MB"""
        return self.server_memory/2


class QueueMixin(RabbitMqMixin):
    """Mixin that creates a RabbitMQ user and host based on the Fabric env."""

    def __init__(self, *args, **kwargs):
        super(QueueMixin, self).__init__(*args, **kwargs)
        if self.fs_encrypt:
            self.secure_dirs.append('/var/lib/rabbitmq')

    def setup(self):
        """Create the RabbitMQ user and vhost."""

        super(QueueMixin, self).setup()
        self.create_mq_user(env.deploy_user, env.broker_password)
        self.create_mq_vhost(env.vhost)
        self.set_mq_vhost_permissions(env.vhost, env.deploy_user, '".*" ".*" ".*"')


class DbMixin(PostgresMixin):
    """Mixin that creates a database based on the Fabric env."""

    # use the default version in this Ubuntu distro
    postgresql_packages = ['postgresql', 'libpq-dev']
    postgresql_tune = True
    postgresql_shmmax = 107374182400 # 100 GB
    postgresql_shmall = 26214400 # 100 GB / PAGE_SIZE (4096)
    # for help adjusting these settings, see:
    # http://wiki.postgresql.org/wiki/Tuning_Your_PostgreSQL_Server
    # http://wiki.postgresql.org/wiki/Number_Of_Database_Connections
    # http://thebuild.com/presentations/not-my-job-djangocon-us.pdf
    postgresql_settings = {
        # connections
        'max_connections': '80', # _active_ connections are limited by pgbouncer
        # replication settings
        'wal_level': 'hot_standby',
        'hot_standby': 'on',
        'hot_standby_feedback': 'on',
        'max_wal_senders': '3',
        'wal_keep_segments': '3000', # during client deletion 50 or more may be generated per minute; this allows an hour
        # resources - let pgtune set these based on actual machine resources
        #'shared_buffers': '8GB', # 25% of available RAM, up to 8GB
        #'work_mem': '750MB', # (2*RAM)/max_connections
        #'maintenance_work_mem': '1GB', # RAM/16 up to 1GB; high values aren't that helpful
        #'effective_cache_size': '48GB', # between 50-75%, should equal free + cached values in `top`
        # checkpoint settings
        'wal_buffers': '16MB',
        'checkpoint_completion_target': '0.9',
        'checkpoint_timeout': '10min', 
        'checkpoint_segments': '256', # if checkpoints are happening more often than the timeout, increase this up to 256
        # logging
        'log_min_duration_statement': '500',
        'log_checkpoints': 'on',
        'log_lock_waits': 'on',
        'log_temp_files': '0',
        # write optimizations
        'commit_delay': '4000', # delay each commit this many microseconds in case we can do a group commit
        'commit_siblings': '5', # only delay if at least N transactions are in process
        # index usage optimizations
        'random_page_cost': '2', # our DB servers have a lot of RAM and may tend to prefer Seq Scans if this is too high
    }
    postgresql_networks = ['10.0.0.0/8']

    def __init__(self, *args, **kwargs):
        super(DbMixin, self).__init__(*args, **kwargs)
        if self.fs_encrypt:
            self.secure_dirs.append('/var/lib/postgresql')

    def setup(self):
        """Create the Postgres user and database based on the Fabric env."""

        super(DbMixin, self).setup()
        self.pg_allow_replication('%s_repl' % env.database_user,
                                  env.database_password,
                                  self.postgresql_networks)


class DbMasterMixin(DbMixin):
    """Mixin that creates a database based on the Fabric env."""

    def setup(self):
        """Create the Postgres user and database based on the Fabric env."""

        super(DbMasterMixin, self).setup()
        self.create_db_user(env.database_user, password=env.database_password)
        self.create_db(env.database_name, owner=env.database_user)


class DbSlaveMixin(DbMixin):
    """Mixin that creates a database based on the Fabric env."""

    def setup(self):
        """Create the Postgres user and database based on the Fabric env."""

        super(DbSlaveMixin, self).setup()
        if len(env.servers['db-master']) > 0:
            master = env.servers['db-master'][0]
            self.pg_copy_master(master, '%s_repl' % env.database_user,
                                env.database_password)


class AppMixin(PythonMixin):
    """
    Mixin that installs the Python application dependencies, including the appropriate
    versions of Python, PIP, and virtualenv.
    """

    python_packages = ['python2.7', 'python2.7-dev']
    python_pip_version = '1.5.2'
    python_virtualenv_version = '1.11.2'

    @uses_fabric
    def update_meld3(self):
        """
        Installs and updates meld3 to 0.6.7 due to issue with supervisor in
        11.04: http://vandahm.com/articles/how-fix-supervisor-ubuntu-1104/
        """

        self.install_packages(['python-meld3'])
        sudo('pip install -U meld3==0.6.7')

    @uses_fabric
    def install_less(self):
        """
        Adds PPAs for node.js and NPM, installs NPM, and uses NPM to globally
        install the ``lessc`` binary used by django_compressor.
        """

        self.add_ppa('ppa:chris-lea/node.js')
        #In 12.04 npm is included in the chris-lea ppa in the 'nodejs' package
        self.install_packages(['nodejs'])
        sudo('npm install -g less@1.3.3')

    def install_system_packages(self):
        """Installs the required system packages."""

        # Install required system packages for deployment, plus some extras
        # Install pip, and use it to install virtualenv
        packages = env.app_server_packages
        self.install_packages(packages)

    @uses_fabric
    def create_webserver_user(self):
        """Create a user for gunicorn, celery, etc."""

        if env.webserver_user != env.deploy_user: # deploy_user already exists
            sudo('useradd --system %(webserver_user)s' % env)

    def setup(self):
        """
        Creates necessary directories, installs required packages, and copies
        the required SSH keys to the server.
        """

        super(AppMixin, self).setup()
        self.update_meld3()
        self.install_less()
        self.install_system_packages()
        self.create_webserver_user()


class WorkerMixin(AppMixin):
    """Mixin that creates a web application server."""

    swap_multiplier = 4 # create 4x the server's RAM in swap

    def __init__(self, *args, **kwargs):
        super(WorkerMixin, self).__init__(*args, **kwargs)


class WebMixin(AppMixin):
    """Mixin that creates a web application server."""

    swap_multiplier = 0 # no swap on the web servers (unhealthy servers will be replaced by Auto Scaling)

    def __init__(self, *args, **kwargs):
        super(WebMixin, self).__init__(*args, **kwargs)

    def setup(self):
        """Installs nginx."""

        super(WebMixin, self).setup()
        self.install_packages(['nginx'])


class CacheInstance(QueueMixin, CacheMixin, SessionMixin, BaseInstance):
    pass


class DbMasterInstance(DbMasterMixin, BaseInstance):
    pass


class DbSlaveInstance(DbSlaveMixin, BaseInstance):
    pass


class WorkerInstance(WorkerMixin, BaseInstance):
    pass


class WebInstance(WebMixin, BaseInstance):
    pass


class CombinedInstance(DbMasterMixin, WebMixin, BaseInstance):
    pass
