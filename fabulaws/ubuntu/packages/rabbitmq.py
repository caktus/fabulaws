from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import uses_fabric
from fabulaws.ubuntu.packages.base import AptMixin


class RabbitMqMixin(AptMixin):
    """
    FabulAWS Ubuntu mixin that configures RabbitMQ
    """

    package_name = 'rabbitmq'
    rabbitmq_packages = ['rabbitmq-server']

    @uses_fabric
    def rabbitmq_service(self, cmd):
        sudo('service rabbitmq-server {0}'.format(cmd))

    def secure_directories(self, *args, **kwargs):
        super(RabbitMqMixin, self).secure_directories(*args, **kwargs)
        # make sure we restart in case we've been moved to a secure directory
        self.rabbitmq_service('restart')

    @uses_fabric
    def rabbitmq_command(self, command):
        """Run a rabbitmqctl command."""

        sudo(u'rabbitmqctl %s' % command)

    def create_mq_user(self, username, password):
        """Create a rabbitmq user."""

        self.rabbitmq_command(u'add_user %s %s' % (username, password))

    def create_mq_vhost(self, name):
        """Create a rabbitmq vhost."""

        self.rabbitmq_command(u'add_vhost %s' % name)

    def set_mq_vhost_permissions(self, vhost, username, permissions='".*" ".*" ".*"'):
        """Set permssions for a user on a given vhost."""

        self.rabbitmq_command(u'set_permissions -p %s %s %s' % (vhost, username, permissions))


class RabbitMqOfficialMixin(RabbitMqMixin):
    """
    Installs RabbitMQ from the official upstream APT repository.
    """

    rabbitmq_aptrepo = ('http://www.rabbitmq.com/debian/', 'testing', 'main', '056E8E56')
    rabbitmq_packages = ['rabbitmq-server']
