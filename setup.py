from setuptools import setup, find_packages

setup(
    name='fabulaws',
    version=__import__('fabulaws').__version__,
    author='Caktus Consulting Group',
    author_email='solutions@caktusgroup.com',
    packages=find_packages(),
    include_package_data=True,
    url='http://github.com/caktus/fabulaws/',
    license='BSD',
    description='Simple tool for interacting with AWS in Python',
    classifiers=[
        'Topic :: System :: Systems Administration',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Development Status :: 4 - Beta',
        'Operating System :: OS Independent',
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
    ],
    long_description=open('README.rst').read(),
    install_requires=[
        'pyyaml',
        'boto>=2.39,<3',
        'fabric3',
    ]
)
