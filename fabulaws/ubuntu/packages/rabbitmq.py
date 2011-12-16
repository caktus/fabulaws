from fabric.api import *
from fabric.contrib import files

from fabulaws.decorators import uses_fabric


class RabbitMqMixin(object):
    """
    FabulAWS Ubuntu mixin that configures RabbitMQ
    """

    rabbitmq_ppa = None
    rabbitmq_packages = ['rabbitmq-server']

    def setup(self):
        """
        Postgres mixin
        """
        super(RabbitMqMixin, self).setup()
        if self.rabbitmq_ppa:
            self.add_ppa(self.rabbitmq_ppa)
        self.install_packages(self.rabbitmq_packages)

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
