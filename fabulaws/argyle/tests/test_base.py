import jinja2

from fabric.api import env, settings
from mock import Mock, patch

from .utils import unittest, ArgyleTest
from argyle.base import upload_template


class UploadTemplateTest(ArgyleTest):

    package = 'argyle.base'
    patched_commands = ['local', 'run', 'sudo', 'put', 'files', ]

    def test_default_jinja_loader(self):
        "The default template are loaded from the argyle package."
        with patch('argyle.base.Environment') as mock_environment:
            upload_template('foo.txt', '/tmp/')
            self.assertTrue(mock_environment.called)
            args, kwargs = mock_environment.call_args
            loader = kwargs['loader']
            self.assertTrue(isinstance(loader, jinja2.ChoiceLoader))
            self.assertEqual(len(loader.loaders), 1)
            self.assertTrue(isinstance(loader.loaders[0], jinja2.PackageLoader))

    def test_additional_template_directories(self):
        "Additional template directories should come before defaults."
        with settings(ARGYLE_TEMPLATE_DIRS=('tests/templates', )):
            with patch('argyle.base.Environment') as mock_environment:
                upload_template('foo.txt', '/tmp/')
                self.assertTrue(mock_environment.called)
                args, kwargs = mock_environment.call_args
                loader = kwargs['loader']
                self.assertTrue(isinstance(loader, jinja2.ChoiceLoader))
                self.assertEqual(len(loader.loaders), 2)
                self.assertTrue(isinstance(loader.loaders[0], jinja2.FileSystemLoader))
        
    def test_default_template_context(self):
        "The fabric env should be the default template context."
        with patch('argyle.base.Environment') as mock_environment:
            mock_env = Mock()
            mock_template = Mock()
            mock_env.get_or_select_template.return_value = mock_template
            mock_environment.return_value = mock_env
            upload_template('foo.txt', '/tmp/')
            self.assertTrue(mock_template.render.called)
            args, kwargs = mock_template.render.call_args
            context = args[0]
            self.assertEqual(context, env)

    def test_additional_template_context(self):
        "Additional template context should be passed to the template render."
        with patch('argyle.base.Environment') as mock_environment:
            mock_env = Mock()
            mock_template = Mock()
            mock_env.get_or_select_template.return_value = mock_template
            mock_environment.return_value = mock_env
            extra = {'foo': 'bar'}
            upload_template('foo.txt', '/tmp/', context=extra)
            self.assertTrue(mock_template.render.called)
            args, kwargs = mock_template.render.call_args
            context = args[0]
            expected = env.copy()
            expected.update(extra)
            self.assertEqual(context, expected)

    def test_destination(self):
        "Destination should be used for putting template on the server."
        with patch('argyle.base.Environment') as mock_environment:
            upload_template('foo.txt', '/tmp/')
            put = self.mocks['put']
            self.assertTrue(put.called)
            args, kwargs = put.call_args
            self.assertEqual(kwargs['remote_path'], '/tmp/foo.txt')

    def test_destination_test(self):
        "Check if destination is a directory for constucting destination filename."
        with patch('argyle.base.Environment') as mock_environment:
            upload_template('foo.txt', '/tmp/')
            self.assertRunCommand('test -d /tmp/')

    def test_destination_test_sudo(self):
        "Destination check will use sudo if the upload requires sudo."
        with patch('argyle.base.Environment') as mock_environment:
            upload_template('foo.txt', '/tmp/', use_sudo=True)
            self.assertSudoCommand('test -d /tmp/')

    def test_destination_filename(self):
        "If destination is a direction use file name from template."
        run = self.mocks['run']
        result = Mock()
        result.succeeded = False # Not a directory
        run.return_value = result
        with patch('argyle.base.Environment') as mock_environment:
            upload_template('foo.txt', '/tmp/bar.txt')
            put = self.mocks['put']
            self.assertTrue(put.called)
            args, kwargs = put.call_args
            self.assertEqual(kwargs['remote_path'], '/tmp/bar.txt')

    def test_upload_tempalte_list(self):
        "Filename can be a list of filename for get_or_select_template."
        with patch('argyle.base.Environment') as mock_environment:
            mock_env = Mock()
            mock_template = Mock()
            mock_template.filename = 'bar.txt' # Second template is used
            mock_env.get_or_select_template.return_value = mock_template
            mock_environment.return_value = mock_env
            upload_template(['foo.txt', 'bar.txt'] , '/tmp/')
            put = self.mocks['put']
            self.assertTrue(put.called)
            args, kwargs = put.call_args
            self.assertEqual(kwargs['remote_path'], '/tmp/bar.txt')

    def test_use_sudo(self):
        "Use sudo should be used for putting template on the server."
        with patch('argyle.base.Environment') as mock_environment:
            upload_template('foo.txt', '/tmp/', use_sudo=True)
            put = self.mocks['put']
            sudo = self.mocks['sudo']
            self.assertTrue(put.called)
            self.assertTrue(sudo.called)
            args, kwargs = put.call_args
            self.assertEqual(kwargs['use_sudo'], True)


if __name__ == '__main__':
    unittest.main()
