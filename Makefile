run:
	source venv/bin/activate && cd src && python3 bot.py

build-img:
	docker build
