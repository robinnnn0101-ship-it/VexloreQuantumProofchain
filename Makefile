.PHONY: test lint run docker

test:
	python3 -m pytest tests/ -q

lint:
	black --check .

run:
	python3 vexlore_chain.py

docker:
	docker build -t vexlore .
	docker run -p 5000:5000 vexlore
