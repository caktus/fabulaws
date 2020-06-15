from mock import patch

from .utils import unittest, ArgyleTest
from argyle import nginx


class NginxTest(ArgyleTest):
    "Base for setting up necessary patches."

    package = 'argyle.nginx'
    patched_commands = ['sudo', 'files', 'upload_template', 'restart_service', ]


class EnableDisableSitesTest(NginxTest):
    "Enabling and disabling site configurations."

    def test_remove_default_site(self):
        "Remove default site if it exists."
        self.mocks['files'].exists.return_value = True
        nginx.remove_default_site()
        self.assertSudoCommand('rm /etc/nginx/sites-enabled/default')

    def test_default_site_already_removed(self):
        "Ignore removing default site if it is already removed."
        self.mocks['files'].exists.return_value = False
        nginx.remove_default_site()
        self.assertFalse(self.mocks['sudo'].called)

    def test_enable_site(self):
        "Enable a site in sites-available."
        self.mocks['files'].exists.return_value = True
        nginx.enable_site('foo')
        self.assertSudoCommand('ln -s -f /etc/nginx/sites-available/foo /etc/nginx/sites-enabled/foo')
        # Restart should be called
        self.assertTrue(self.mocks['restart_service'].called)

    def test_enable_missing_site(self):
        "Abort if attempting to enable a site which is not available."
        self.mocks['files'].exists.return_value = False
        with patch('argyle.nginx.abort') as abort:
            nginx.enable_site('foo')
            self.assertTrue(abort.called)
            # Restart should not be called
            self.assertFalse(self.mocks['restart_service'].called)

    def test_disable_site(self):
        "Remove a site from sites-enabled."
        self.mocks['files'].exists.return_value = True
        nginx.disable_site('foo')
        self.assertSudoCommand('rm /etc/nginx/sites-enabled/foo')
        # Restart should be called
        self.assertTrue(self.mocks['restart_service'].called)

    def test_disable_site_already_removed(self):
        "Ignore removing a site if it is already removed."
        self.mocks['files'].exists.return_value = False
        nginx.disable_site('foo')
        self.assertFalse(self.mocks['sudo'].called)
        # Restart should not be called
        self.assertFalse(self.mocks['restart_service'].called)


class UploadSiteTest(NginxTest):
    "Upload site configuration via template."

    def test_default_upload(self):
        "Upload default site configuration."
        with patch('argyle.nginx.enable_site') as enable:
            nginx.upload_nginx_site_conf('test')
            # No additional context by default
            self.assertTemplateContext(None)
            # Upload template will look for templates in the given order
            self.assertTemplateUsed([u'nginx/test.conf', u'nginx/site.conf'])
            self.assertTemplateDesination('/etc/nginx/sites-available/test')
            # Site will be enabled by default
            self.assertTrue(enable.called)

    def test_explicit_template_name(self):
        "Override template name for upload."
        with patch('argyle.nginx.enable_site') as enable:
            nginx.upload_nginx_site_conf('test', template_name='test.conf')
            # Upload template will look for templates in the given order
            self.assertTemplateUsed('test.conf')
            self.assertTemplateDesination('/etc/nginx/sites-available/test')

    def test_additional_context(self):
        "Pass additional context to the template."
        with patch('argyle.nginx.enable_site') as enable:
            nginx.upload_nginx_site_conf('test', context={'foo': 'bar'})
            self.assertTemplateContext({'foo': 'bar'})

    def test_upload_without_enabling(self):
        "Upload site configuration but don't enable."
        with patch('argyle.nginx.enable_site') as enable:
            nginx.upload_nginx_site_conf('test', enable=False)
            self.assertFalse(enable.called)


if __name__ == '__main__':
    unittest.main()
