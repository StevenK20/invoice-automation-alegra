.PHONY: install demo test samples clean
install:
	pip install -r requirements-dev.txt
demo:
	python run_demo.py
test:
	python -m pytest -q
samples:
	python scripts/generate_samples.py
clean:
	rm -rf output .pytest_cache
