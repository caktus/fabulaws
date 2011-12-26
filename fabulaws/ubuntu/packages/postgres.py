import re

from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import *


class PostgresMixin(object):
    """
    FabulAWS Ubuntu mixin that installs and configures PostgresSQL.
    """
    postgresql_ppa = None
    postgresql_packages = ['postgresql', 'libpq-dev']
    postgresql_tune = False
    postgresql_tune_type = 'Web'
    postgresql_shmmax = 536870912 # 512 MB
    postgresql_settings = {}

    @cached_property()
    @uses_fabric
    def pg_version(self):
        version = run('pg_config --version')
        return re.findall(r'(\d+\.\d+)\.?\d+?', version)[0]

    @cached_property()
    @uses_fabric
    def pg_conf(self):
        return '/etc/postgresql/%s/main/postgresql.conf' % self.pg_version

    @uses_fabric
    def pg_set_str(self, setting, value):
        # fabric doesn't properly escape single quotes for sed commands, so run sed manually instead
        sudo('sed -i.bak -r -e "s/#? ?{setting} = \'.+\'/{setting} = \'{value}\'/g" '
             '{pg_conf}'.format(setting=setting, value=value, pg_conf=self.pg_conf))

    @uses_fabric
    def pg_set(self, setting, value):
        sudo('sed -i.bak -r -e "s/#? ?{setting} = \w+/{setting} = {value}/g" '
             '{pg_conf}'.format(setting=setting, value=value, pg_conf=self.pg_conf))

    @uses_fabric
    def pg_cmd(self, action):
        """Run the specified action (e.g., start, stop, restart) on the postgresql server."""

        sudo('service postgresql %s' % action)

    @uses_fabric
    def pg_tune_config(self, restart=True):
        """Tune the postgresql configuration using pgtune"""

        self.install_packages(['pgtune'])
        old = '%s.bak' % self.pg_conf
        new = '%s.new' % self.pg_conf
        db_type = self.postgresql_tune_type
        sudo('pgtune -T %s -i %s -o %s' % (db_type, self.pg_conf, new))
        sudo('mv %s %s' % (self.pg_conf, old))
        sudo('mv %s %s' % (new, self.pg_conf))
        shmmax = self.postgresql_shmmax
        sudo('sysctl -w kernel.shmmax=%s' % shmmax)
        files.append('/etc/sysctl.conf', 'kernel.shmmax=%s' % shmmax, use_sudo=True)
        if restart:
            self.pg_cmd('restart')

    @uses_fabric
    def pg_allow_from(self, ip_ranges, restart=True):
        """Allow external connections from the given IP range."""

        self.pg_set_str('listen_addresses', '*')
        pghba = '/etc/postgresql/%s/main/pg_hba.conf' % self.pg_version
        for ip_range in ip_ranges:
            hostssl_line = 'hostssl    all    all    %s    md5' % ip_range
            files.append(pghba, hostssl_line, use_sudo=True)
        if restart:
            self.pg_cmd('restart')

    def pg_update_settings(self, settings, restart=True):
        """Update the specified settings according to the given dictionary."""

        for k, v in settings.items():
            self.pg_set(k, v)
        if restart:
            self.pg_cmd('restart')

    def setup(self):
        """Postgres mixin"""

        super(PostgresMixin, self).setup()
        if self.postgresql_ppa:
            self.add_ppa(self.postgresql_ppa)
        self.install_packages(self.postgresql_packages)
        if self.postgresql_tune:
            self.pg_tune_config(restart=False)
        self.pg_allow_from(self.postgresql_networks, restart=False)
        self.pg_update_settings(self.postgresql_settings, restart=False)
        self.pg_cmd('restart')

    @uses_fabric
    def create_db_user(self, username, password=None, flags=None):
        """Create a databse user."""

        flags = flags or u'-D -A -R'
        sudo(u'createuser %s %s' % (flags, username), user=u'postgres')
        if password:
            self.change_db_user_password(username, password)

    @uses_fabric
    def change_db_user_password(self, username, password):
        """Change a db user's password."""

        sql = "ALTER USER %s WITH PASSWORD '%s'" % (username, password)
        sudo('psql -c "%s"' % sql, user='postgres')

    @uses_fabric
    def create_db(self, name, owner=None, encoding=u'UTF-8'):
        """Create a Postgres database."""

        flags = u''
        if encoding:
            flags = u'-E %s' % encoding
        if owner:
            flags = u'%s -O %s' % (flags, owner)
        sudo('createdb %s %s' % (flags, name), user='postgres')
