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
    postgresql_tune = False
    postgresql_tune_type = 'Web'
    postgresql_shmmax = 536870912 # 512 MB
    postgresql_shmall = 2097152
    postgresql_settings = {}
    postgresql_disable_oom = True

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

        # XXX: does not support differing master/slave pg versions
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
        with master_db:
            now = datetime.datetime.today().strftime('%m-%d-%Y_%H-%M-%S')
            backup_dir = '/tmp/pg_basebackup_{0}'.format(now)
            sudo('{pg_bin}/pg_basebackup -F t -z -x -D {backup_dir}'
                 ''.format(pg_bin=self.pg_bin, backup_dir=backup_dir), user='postgres')
            sudo('chmod -R a+rx {0}'.format(backup_dir))
        sshagent_run('scp -o StrictHostKeyChecking=no '
                     '{user}@{master}:{backup_dir}/base.tar.gz '
                     '{backup_dir}.tar.gz'
                     ''.format(master=master_db.internal_ip, user=env.user,
                               backup_dir=backup_dir))
        with cd(self.pg_data):
            recovery = 'recovery.conf'
            sudo('echo "standby_mode = \'on\'" > {file_}'
                 ''.format(file_=recovery), user='postgres')
            sudo('echo "primary_conninfo = \'host={host} user={user} '
                 'password={password}\'" >> {file_}'
                 ''.format(host=master_db.internal_ip, file_=recovery,
                           user=user, password=password), user='postgres')
            sudo('tar xzf {0}.tar.gz'.format(backup_dir), user='postgres')
        self.pg_cmd('start')
        with master_db:
            sudo('rm -rf %s' % backup_dir)

    @uses_fabric
    def pg_promote(self):
        sudo('{0}/pg_ctl -D {1} promote'.format(self.pg_bin, self.pg_data),
             user='postgres')

    def secure_directories(self, *args, **kwargs):
        # make sure we stop first in case we're being moved to a secure directory
        self.pg_cmd('stop', fail=False)
        super(PostgresMixin, self).secure_directories(*args, **kwargs)
        self.pg_cmd('start', fail=False)

    def setup(self):
        """Postgres mixin"""

        super(PostgresMixin, self).setup()
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
