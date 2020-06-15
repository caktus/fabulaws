from fabulaws.argyle.base import upload_template
from fabric.api import sudo, task
from fabric.contrib import files


@task
def supervisor_command(command):
    """Run a supervisorctl command."""

    sudo(u'supervisorctl %s' % command)


@task
def upload_supervisor_app_conf(app_name, template_name=None, context=None):
    """Upload Supervisor app configuration from a template."""

    default = {'app_name': app_name}
    context = context or {}
    default.update(context)
    template_name = template_name or [u'supervisor/%s.conf' % app_name, u'supervisor/base.conf']
    destination = u'/etc/supervisor/conf.d/%s.conf' % app_name
    upload_template(template_name, destination, context=default, use_sudo=True)
    supervisor_command(u'update')


@task
def remove_supervisor_app(app_name):
    """Remove Supervisor app configuration."""

    app = u'/etc/supervisor/conf.d/%s.conf' % app_name
    if files.exists(app):
        sudo(u'rm %s' % app)
        supervisor_command(u'update')


@task
def upload_celery_conf(command='celery', app_name=None, template_name=None, context=None):
    """Upload Supervisor configuration for a celery command."""

    app_name = app_name or command
    default = {'app_name': app_name, 'command': command}
    context = context or {}
    default.update(context)
    template_name = template_name or [u'supervisor/%s.conf' % command, u'supervisor/celery.conf']
    upload_supervisor_app_conf(app_name=app_name, template_name=template_name, context=default)


@task
def upload_gunicorn_conf(command='gunicorn', app_name=None, template_name=None, context=None):
    """Upload Supervisor configuration for a gunicorn server."""
    
    app_name = app_name or command
    default = {'app_name': app_name, 'command': command}
    context = context or {}
    default.update(context)
    template_name = template_name or [u'supervisor/%s.conf' % command, u'supervisor/gunicorn.conf']
    upload_supervisor_app_conf(app_name=app_name, template_name=template_name, context=default)
