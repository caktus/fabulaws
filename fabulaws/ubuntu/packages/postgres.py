import re

from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import uses_fabric


class PostgresMixin(object):
    """
    FabulAWS Ubuntu mixin that installs and configures PostgresSQL.
    """
    postgresql_ppa = None
    postgresql_packages = ['postgresql', 'libpq-dev']
    postgresql_tune = False
    postgresql_tune_type = 'Web'
    postgresql_shmmax = 536870912 # 512 MB

    @uses_fabric
    def get_version(self):
        version = run('pg_config --version')
        return re.findall(r'(\d+\.\d+)\.?\d+?', version)[0]

    @uses_fabric
    def postgresql_tune_config(self):
        """Tune the postgresql configuration using pgtune"""

        self.install_packages(['pgtune'])
        version = self.get_version()
        current = '/etc/postgresql/%s/main/postgresql.conf' % version
        old = '%s.bak' % current
        new = '%s.new' % current
        db_type = self.postgresql_tune_type
        sudo('pgtune -T %s -i %s -o %s' % (db_type, current, new))
        sudo('mv %s %s' % (current, old))
        sudo('mv %s %s' % (new, current))
        shmmax = self.postgresql_shmmax
        sudo('sysctl -w kernel.shmmax=%s' % shmmax)
        files.append('/etc/sysctl.conf', 'kernel.shmmax=%s' % shmmax, use_sudo=True)
        sudo('service postgresql restart')

    @uses_fabric
    def allow_external_connections(self, ip_range):
        """Allow external connections from the given IP range."""

        version = self.get_version()
        pghba = '/etc/postgresql/%s/main/pg_hba.conf' % version
        pgconf = '/etc/postgresql/%s/main/postgresql.conf' % version
        hostssl_line = 'hostssl    all    all    %s    md5' % ip_range
        files.append(pghba, hostssl_line, use_sudo=True)
        # fabric doesn't properly escape single quotes for sed commands, so run sed manually instead
        sudo('sed -i.bak -r -e "s/#listen_addresses = \'localhost\'/listen_addresses = \'*\'/g" %s' % pgconf)
        sudo('service postgresql restart')

    def setup(self):
        """Postgres mixin"""

        super(PostgresMixin, self).setup()
        if self.postgresql_ppa:
            self.add_ppa(self.postgresql_ppa)
        self.install_packages(self.postgresql_packages)
        if self.postgresql_tune:
            self.postgresql_tune_config()

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
