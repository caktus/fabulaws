import re
import datetime

from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import *
from fabulaws.api import *
from fabulaws.ubuntu.packages.base import AptMixin


class PostgresMixin(AptMixin):
    """
    FabulAWS Ubuntu mixin that installs and configures PostgresSQL.
    """
    package_name = 'postgresql'

    postgresql_packages = ['postgresql', 'libpq-dev']
    postgresql_tune = True
    postgresql_tune_type = 'Web'
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
        # resources - set these dynamically based on actual machine resources (see pg_resource_settings())
        #'shared_buffers': '8GB',
        #'work_mem': '750MB',
        #'maintenance_work_mem': '1GB',
        #'effective_cache_size': '48GB',
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
    postgresql_networks = ['10.0.0.0/8', '172.16.0.0/12']
    postgresql_disable_oom = False

    def __init__(self, *args, **kwargs):
        db_settings = kwargs.pop('db_settings', {}).copy()
        for key in ['postgresql_packages', 'postgresql_tune', 'postgresql_tune_type',
                    'postgresql_shmmax', 'postgresql_shmall',
                    'postgresql_networks', 'postgresql_disable_oom']:
            if key in db_settings:
                setattr(self, key, db_settings.pop(key))

        # Override individual default settings with whatever settings the project has specified.
        self.postgresql_settings = self.postgresql_settings.copy()
        self.postgresql_settings.update(db_settings.pop('postgresql_settings', {}))

        if db_settings:
            # There were keys we did not recognize; complain rather than let the
            # user think we're applying setttings that we're not.
            raise ValueError("Unrecognized keys in 'db_settings': %s" % ', '.join(db_settings.keys()))

        super(PostgresMixin, self).__init__(*args, **kwargs)

    @property
    def pgpass(self):
        return '/var/lib/postgresql/.pgpass'

    @cached_property()
    @uses_fabric
    def pg_version(self):
        version = run('pg_config --version')
        return re.findall(r'(\d+\.\d+)\.?\d+?', version)[0]

    @cached_property()
    @uses_fabric
    def pg_conf(self):
        return '/etc/postgresql/{0}/main/postgresql.conf'.format(self.pg_version)

    @cached_property()
    @uses_fabric
    def pg_data(self):
        return '/var/lib/postgresql/{0}/main'.format(self.pg_version)

    @cached_property()
    @uses_fabric
    def pg_hba(self):
        return '/etc/postgresql/{0}/main/pg_hba.conf'.format(self.pg_version)

    @cached_property()
    @uses_fabric
    def pg_bin(self):
        return '/usr/lib/postgresql/{0}/bin'.format(self.pg_version)

    @uses_fabric
    def sed(self, before, after, file_):
        # fabric doesn't properly escape single quotes for sed commands, so run sed manually instead
        sudo('sed -i.bak -r -e "s/{before}/{after}/g" {file_}'
             ''.format(before=before, after=after, file_=file_))

    @uses_fabric
    def pg_set_str(self, setting, value):
        self.sed('^#? ?{setting} = \'.+\''.format(setting=setting),
                 '{setting} = \'{value}\''.format(setting=setting, value=value),
                 self.pg_conf)

    @uses_fabric
    def pg_set(self, setting, value):
        self.sed('^#? ?{setting} = \S+'.format(setting=setting),
                 '{setting} = {value}'.format(setting=setting, value=value),
                 self.pg_conf)

    @uses_fabric
    def pg_cmd(self, action, fail=True):
        """Run the specified action (e.g., start, stop, restart) on the postgresql server."""

        if fail or files.exists('/etc/init/postgresql.conf'):
            sudo('service postgresql %s' % action)

    @uses_fabric
    def pg_resource_settings(self):
        """
        Calculate a few resource settings dynamically. Will be overridden by
        pgtune or manually specified settings, if any.
        """
        mem = self.server_memory
        max_connections = int(self.postgresql_settings['max_connections'])
        # pgtune isn't available anymore as of Ubuntu 16.04, so calculate a few
        # basic resources dynamically just in case
        return {
            # 25% of available RAM, up to 8GB
            'shared_buffers': '%sMB' % int(min(mem * 0.25, 8096)),
            # (2*RAM)/max_connections
            'work_mem': '%sMB' % int((mem * 2) / max_connections),
            # RAM/16 up to 1GB; high values aren't that helpful
            'maintenance_work_mem': '%sMB' % int(min(mem / 16, 1024)),
            # between 50-75%, should equal free + cached values in `top`
            'effective_cache_size': '%sMB' % int(mem * 0.7),
        }

    @uses_fabric
    def pg_tune_config(self, restart=True):
        """Tune the postgresql configuration using pgtune"""

        self.install_packages(['pgtune'])
        old = '%s.bak' % self.pg_conf
        new = '%s.new' % self.pg_conf
        db_type = self.postgresql_tune_type
        conns = ''
        if 'max_connections' in self.postgresql_settings:
            conns = '-c %s' % self.postgresql_settings['max_connections']
        sudo('pgtune -T %s -i %s -o %s %s' % (db_type, self.pg_conf, new, conns))
        sudo('mv %s %s' % (self.pg_conf, old))
        sudo('mv %s %s' % (new, self.pg_conf))
        if restart:
            self.pg_cmd('restart')

    @uses_fabric
    def pg_set_sysctl_params(self, restart=True):
        sudo('sysctl -w kernel.shmmax=%s' % self.postgresql_shmmax)
        files.append('/etc/sysctl.conf', 'kernel.shmmax=%s'
                     '' % self.postgresql_shmmax, use_sudo=True)
        sudo('sysctl -w kernel.shmall=%s' % self.postgresql_shmall)
        files.append('/etc/sysctl.conf', 'kernel.shmall=%s'
                     '' % self.postgresql_shmall, use_sudo=True)
        if self.postgresql_disable_oom:
            sudo('sysctl -w vm.overcommit_memory=2')
            files.append('/etc/sysctl.conf', 'vm.overcommit_memory=2',
                         use_sudo=True)
        if restart:
            self.pg_cmd('restart')

    @uses_fabric
    def pg_allow_from(self, ip_ranges, restart=True):
        """Allow external connections from the given IP range."""

        self.pg_set_str('listen_addresses', '*')
        files.uncomment(self.pg_hba, 'local +replication', use_sudo=True)
        for ip_range in ip_ranges:
            hostssl_line = 'hostssl    all    all    %s    md5' % ip_range
            files.append(self.pg_hba, hostssl_line, use_sudo=True)
        if restart:
            self.pg_cmd('restart')

    def pg_update_settings(self, settings, restart=True):
        """Update the specified settings according to the given dictionary."""

        for k, v in settings.items():
            self.pg_set(k, v)
        if restart:
            self.pg_cmd('restart')

    @uses_fabric
    def pg_allow_replication(self, user, password, ip_ranges, restart=True):
        """Creates a user for replication and enables replication in pg_hba.conf."""

        # XXX: does not support differing primary/replica pg versions
        self.create_db_user(user, password, replication=True)
        files.uncomment(self.pg_hba, 'local +replication', use_sudo=True)
        for ip_range in ip_ranges:
            hostssl_line = 'hostssl    replication    all    %s    md5' % ip_range
            files.append(self.pg_hba, hostssl_line, use_sudo=True)
        if restart:
            sudo('service postgresql restart')

    @uses_fabric
    def pg_copy_master(self, master_db, user, password):
        """Replaces this database host with a copy of the data at master_host."""

        self.pg_cmd('stop')
        sudo('rm -rf {0}'.format(self.pg_data))
        pgpass_line = ':'.join([master_db.internal_ip, '*', 'replication', user, password])
        sudo('echo "{line}" > {file_}'
             ''.format(file_=self.pgpass, line=pgpass_line), user='postgres')
        sudo('chmod 600 {0}'.format(self.pgpass), user='postgres')
        sudo('{pg_bin}/pg_basebackup -x -D {pg_data} -P -h {host} -U {user}'
             ''.format(pg_bin=self.pg_bin, pg_data=self.pg_data,
                       host=master_db.internal_ip, user=user),
             user='postgres')
        with cd(self.pg_data):
            recovery = 'recovery.conf'
            sudo('echo "standby_mode = \'on\'" > {file_}'
                 ''.format(file_=recovery), user='postgres')
            sudo('echo "primary_conninfo = \'host={host} user={user} '
                 'password={password}\'" >> {file_}'
                 ''.format(host=master_db.internal_ip, file_=recovery,
                           user=user, password=password), user='postgres')
            sudo('chmod 600 {0}'.format(recovery), user='postgres')
            sudo('ln -s /etc/ssl/certs/ssl-cert-snakeoil.pem server.crt')
            sudo('ln -s /etc/ssl/private/ssl-cert-snakeoil.key server.key')
        self.pg_cmd('start')

    @uses_fabric
    def pg_promote(self):
        sudo('{0}/pg_ctl -D {1} promote'.format(self.pg_bin, self.pg_data),
             user='postgres')

    def bind_app_directories(self, *args, **kwargs):
        # make sure we stop first in case we're being moved to a secure directory
        self.pg_cmd('stop', fail=False)
        super(PostgresMixin, self).bind_app_directories(*args, **kwargs)
        self.pg_cmd('start', fail=False)

    def setup(self):
        """Postgres mixin"""

        super(PostgresMixin, self).setup()
        if 'max_connections' in self.postgresql_settings:
            self.pg_update_settings(self.pg_resource_settings(), restart=False)
        if self.postgresql_tune:
            self.pg_tune_config(restart=False)
        self.pg_set_sysctl_params(restart=False)
        self.pg_allow_from(self.postgresql_networks, restart=False)
        self.pg_update_settings(self.postgresql_settings, restart=False)
        self.pg_cmd('restart')

    @uses_fabric
    def sql(self, sql):
        sudo('psql -c "%s"' % sql, user='postgres')

    @uses_fabric
    def create_db_user(self, username, password=None, **kwargs):
        """Create a database user."""

        defaults = {'login': True}
        defaults.update(kwargs)
        options = [k.upper() for k in defaults if k]
        options.extend(['NO' + k.upper() for k in defaults if not k])
        sql = "CREATE ROLE {name} {options}".format(name=username, options=' '.join(options))
        if password is not None:
            sql += " PASSWORD '%s'" % password
        self.sql(sql)

    @uses_fabric
    def change_db_user_password(self, username, password):
        """Change a db user's password."""

        self.sql("ALTER USER %s WITH PASSWORD '%s'" % (username, password))

    @uses_fabric
    def create_db(self, name, owner=None, encoding=u'UTF-8'):
        """Create a Postgres database."""

        flags = u''
        if encoding:
            flags = u'-E %s' % encoding
        if owner:
            flags = u'%s -O %s' % (flags, owner)
        sudo('createdb %s %s' % (flags, name), user='postgres')
