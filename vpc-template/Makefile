.DEFAULT_GOAL := vpc

check:
	flake8 stack/
	isort --recursive --check-only --diff stack/

vpc:
	python -c 'import stack' > cloudformation-vpc-template.json
