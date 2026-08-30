.PHONY: test run image

test:
	python3 -m unittest discover -s tests -v

run:
	python3 -m app --config-dir .dev-config --listen 127.0.0.1:9080

image:
	docker build -f Containerfile -t wise-route-manager:dev .

