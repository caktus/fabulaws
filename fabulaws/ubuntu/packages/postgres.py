from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import uses_fabric


class PostgresMixin(object):
    """
    FabulAWS Ubuntu mixin that installs and configures PostgresSQL.
    """
    postgresql_ppa = None
    postgresql_packages = ['postgresql', 'postgresql-common']

    def setup(self):
        """
        Postgres mixin
        """
        super(PostgresMixin, self).setup()
        if self.postgresql_ppa:
            self.add_ppa(self.postgresql_ppa)
        self.install_packages(self.postgresql_packages)

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
