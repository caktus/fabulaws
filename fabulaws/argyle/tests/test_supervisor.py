from mock import patch

from .utils import unittest, ArgyleTest
from argyle import supervisor


class SupervisorTest(ArgyleTest):
    "Base for setting up necessary patches."

    package = 'argyle.supervisor'
    patched_commands = ['sudo', 'upload_template', 'files', ]


class SupervisorCommandTest(SupervisorTest):
    "Calling supervisorctl commands."

    def test_update_command(self):
        "Call update command."
        supervisor.supervisor_command("update")
        self.assertSudoCommand('supervisorctl update')

    def test_restart_all(self):
        "Restart all supervisor managed processes."
        supervisor.supervisor_command("restart all")
        self.assertSudoCommand('supervisorctl restart all')


class UploadConfigurationTest(SupervisorTest):
    "Uploading a configuration for a supervisor managed command."

    def test_default_upload(self):
        "Upload default configuration."
        supervisor.upload_supervisor_app_conf('test')
        # Default context
        self.assertTemplateContext({'app_name': 'test'})
        # Upload template will look for templates in the given order
        self.assertTemplateUsed([u'supervisor/test.conf', u'supervisor/base.conf'])
        self.assertTemplateDesination(u'/etc/supervisor/conf.d/test.conf')
        self.assertSudoCommand('supervisorctl update')

    def test_alternate_template_name(self):
        "Change default template search."
        supervisor.upload_supervisor_app_conf(u'test', template_name=u'bar.conf')
        self.assertTemplateUsed(u'bar.conf')
        self.assertTemplateDesination(u'/etc/supervisor/conf.d/test.conf')

    def test_additional_context(self):
        "Pass additional context to the template."
        supervisor.upload_supervisor_app_conf('test', context={'foo': 'bar'})
        self.assertTemplateContext({'app_name': 'test', 'foo': 'bar'})


class CeleryConfigurationTest(SupervisorTest):
    "Helper for managing Celery processes (celeryd, celerybeat, etc) with supervisor."

    def test_default_upload(self):
        "Upload default configuration."
        supervisor.upload_celery_conf()
        # Default context
        self.assertTemplateContext({'app_name': 'celeryd', 'command': 'celery worker'})
        # Upload template will look for templates in the given order
        self.assertTemplateUsed([u'supervisor/celeryd.conf', u'supervisor/celery.conf'])
        self.assertTemplateDesination(u'/etc/supervisor/conf.d/celeryd.conf')
        self.assertSudoCommand('supervisorctl update')

    def test_alternate_template_name(self):
        "Change default template search."
        supervisor.upload_celery_conf(template_name=u'bar.conf')
        self.assertTemplateUsed(u'bar.conf')
        self.assertTemplateDesination(u'/etc/supervisor/conf.d/celeryd.conf')

    def test_additional_context(self):
        "Pass additional context to the template."
        supervisor.upload_celery_conf(context={'foo': 'bar'})
        self.assertTemplateContext({'app_name': 'celeryd', 'command': 'celery worker', 'foo': 'bar'})

    def test_alternate_command(self):
        "Upload template for another celery command."
        supervisor.upload_celery_conf(command='celery beat')
        self.assertTemplateContext({'app_name': 'celerybeat', 'command': 'celery beat'})
        self.assertTemplateUsed([u'supervisor/celerybeat.conf', u'supervisor/celery.conf'])
        self.assertTemplateDesination(u'/etc/supervisor/conf.d/celerybeat.conf')

    def test_alternate_app_name(self):
        "Use another app name for the celeryd command."
        supervisor.upload_celery_conf(app_name='worker-2')
        self.assertTemplateContext({'app_name': 'worker-2', 'command': 'celery worker'})
        self.assertTemplateUsed([u'supervisor/celeryd.conf', u'supervisor/celery.conf'])
        self.assertTemplateDesination(u'/etc/supervisor/conf.d/worker-2.conf')


class GunicornConfigurationTest(SupervisorTest):
    "Helper for managing Gunicorn servers  with supervisor."

    def test_default_upload(self):
        "Upload default configuration."
        supervisor.upload_gunicorn_conf()
        # Default context
        self.assertTemplateContext({'app_name': 'gunicorn', 'command': 'gunicorn'})
        # Upload template will look for templates in the given order
        self.assertTemplateUsed([u'supervisor/gunicorn.conf', u'supervisor/gunicorn.conf'])
        self.assertTemplateDesination(u'/etc/supervisor/conf.d/gunicorn.conf')
        self.assertSudoCommand('supervisorctl update')

    def test_alternate_template_name(self):
        "Change default template search."
        supervisor.upload_gunicorn_conf(template_name=u'bar.conf')
        self.assertTemplateUsed(u'bar.conf')
        self.assertTemplateDesination(u'/etc/supervisor/conf.d/gunicorn.conf')

    def test_additional_context(self):
        "Pass additional context to the template."
        supervisor.upload_gunicorn_conf(context={'foo': 'bar'})
        self.assertTemplateContext({'app_name': 'gunicorn', 'command': 'gunicorn', 'foo': 'bar'})

    def test_alternate_command(self):
        "Upload template for another gunicorn command."
        supervisor.upload_gunicorn_conf(command='gunicorn_django')
        self.assertTemplateContext({'app_name': 'gunicorn_django', 'command': 'gunicorn_django'})
        self.assertTemplateUsed([u'supervisor/gunicorn_django.conf', u'supervisor/gunicorn.conf'])
        self.assertTemplateDesination(u'/etc/supervisor/conf.d/gunicorn_django.conf')

    def test_alternate_app_name(self):
        "Use another app name for the gunicorn command."
        supervisor.upload_gunicorn_conf(app_name='server-2')
        self.assertTemplateContext({'app_name': 'server-2', 'command': 'gunicorn'})
        self.assertTemplateUsed([u'supervisor/gunicorn.conf', u'supervisor/gunicorn.conf'])
        self.assertTemplateDesination(u'/etc/supervisor/conf.d/server-2.conf')


class DisableAppTest(SupervisorTest):
    "Disabling process managed by supervisor."

    def test_disable_site(self):
        "Remove an supervisor configuration from conf.d."
        self.mocks['files'].exists.return_value = True
        supervisor.remove_supervisor_app('foo')
        self.assertSudoCommand('rm /etc/supervisor/conf.d/foo.conf')
        # Update configuration
        self.assertSudoCommand('supervisorctl update')

    def test_disable_site_already_removed(self):
        "Ignore removing a configuration if it is already removed."
        self.mocks['files'].exists.return_value = False
        supervisor.remove_supervisor_app('foo')
        self.assertFalse(self.mocks['sudo'].called)


if __name__ == '__main__':
    unittest.main()
