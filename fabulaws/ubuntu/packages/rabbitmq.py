import time

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
    rabbitmq_ulimit = 20000

    @uses_fabric
    def rabbitmq_service(self, cmd):
        return sudo('service rabbitmq-server {0}'.format(cmd))

    def secure_directories(self, *args, **kwargs):
        tries = kwargs.pop('rabbitmq_tries', 10)
        sleep = kwargs.pop('rabbitmq_sleep', 2)
        # make sure we stop before proceeding in case we get moved to a secure directory
        self.rabbitmq_service('stop') 
        super(RabbitMqMixin, self).secure_directories(*args, **kwargs)
        # try starting a number of times with warn_only=True, as rabbitmq
        # fails to restart occassionally for unknown reasons
        restarted = False
        for i in range(tries-1):
            with settings(warn_only=True):
                result = self.rabbitmq_service('start')
                if result.return_code == 0:
                    restarted = True
                    break
                else:
                    time.sleep(sleep)
        # if we haven't succeeded yet, start again without warn_only=True
        # and let the failure be handled as usual by Fabric
        if not restarted:
            self.rabbitmq_service('start') 

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

    @uses_fabric
    def rabbitmq_configure(self):
        files.append('/etc/default/rabbitmq-server',
                     'ulimit -n %s' % self.rabbitmq_ulimit, use_sudo=True)
        self.rabbitmq_service('restart')

    def setup(self):
        """Redis mixin"""

        super(RabbitMqMixin, self).setup()
        self.rabbitmq_configure()


class RabbitMqOfficialMixin(RabbitMqMixin):
    """
    Installs RabbitMQ from the official upstream APT repository.
    """

    rabbitmq_aptrepo = ('http://www.rabbitmq.com/debian/', 'testing', 'main', '056E8E56')
    rabbitmq_packages = ['rabbitmq-server']
