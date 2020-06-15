from fabulaws.argyle.base import upload_template
from fabulaws.argyle.system import restart_service
from fabric.api import sudo, task


@task
def rabbitmq_command(command):
    """Run a rabbitmqctl command."""

    sudo(u'rabbitmqctl %s' % command)


@task
def create_user(username, password):
    """Create a rabbitmq user."""

    rabbitmq_command(u'add_user %s %s' % (username, password))


@task
def create_vhost(name):
    """Create a rabbitmq vhost."""

    rabbitmq_command(u'add_vhost %s' % name)


@task
def set_vhost_permissions(vhost, username, permissions='".*" ".*" ".*"'):
    """Set permssions for a user on a given vhost."""

    rabbitmq_command(u'set_permissions -p %s %s %s' % (vhost, username, permissions))


@task
def upload_rabbitmq_environment_conf(template_name=None, context=None, restart=True):
    """Upload RabbitMQ environment configuration from a template."""
    
    template_name = template_name or u'rabbitmq/rabbitmq-env.conf'
    destination = u'/etc/rabbitmq/rabbitmq-env.conf'
    upload_template(template_name, destination, context=context, use_sudo=True)
    if restart:
        restart_service(u'rabbitmq')


@task
def upload_rabbitmq_conf(template_name=None, context=None, restart=True):
    """Upload RabbitMQ configuration from a template."""
    
    template_name = template_name or u'rabbitmq/rabbitmq.config'
    destination = u'/etc/rabbitmq/rabbitmq.config'
    upload_template(template_name, destination, context=context, use_sudo=True)
    if restart:
        restart_service(u'rabbitmq')
