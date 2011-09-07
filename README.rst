FabulAWS
========

`FabulAWS <https://github.com/caktus/fabulaws>`_ is a tool that lets you simply
and easily create new servers, from scratch.  You can do this in an existing
`Fabric <http://www.fabfile.org/>`_ file, or separately in your own
application.

Simple example
--------------
FabulAWS lets you create EC2 instances using a context manager in Python and
easily execute work on that instance. Typical workflow might look like this::

    from fabulaws.ec2 import MicroLucidInstance
    
    with MicroLucidInstance():
        run('uname -a')

If needed, you can extend the instance classes defined in the ``fabulaws.ec2``
module as needed to further customize the instance before presenting it as
a context manager (or using it in your fab file).  To do so, simply extend
the ``setup()`` and ``cleanup()`` methods in one of the existing classes.

Requirements
------------

Dependencies are listed in the accompanying PIP requirements file.  To install
them, run the following command::

    pip install -r requirements.txt

Please refer to the `documentation <http://fabulaws.readthedocs.org/>`_ for more details.

Development by `Caktus Consulting Group <http://www.caktusgroup.com/>`_.
