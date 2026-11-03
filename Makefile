.PHONY: run test clean

run:
	python3 vexlore_chain.py

test:
	python3 -m unittest discover tests -v

clean:
	rm -rf __pycache__ *.pyc data/ wallet/
