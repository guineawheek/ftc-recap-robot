# FTC Recap Robot

Ever get annoyed that making recaps by hand is too hard and labor-intensive? Not a problem! 
With the power of automation, we can have machines make them for us.


## Setup:

You need: 

* python 3.9 (3.10+ doesn't work because the tts this uses pytorch)
* ffmpeg in your PATH
* an FTC-Events API key

Rough install steps:
```
python3.9 -m venv venv
. venv/bin/activate
pip install TTS yt-dlp jupyter
```

Make a file called `token` and provde the following:

```json
{
	"username": "[ftc-events username]",
	"token": "[ftc-events token]",
}
```


## Running:

Run the jupyter notebook and edit it to get results. You may need to edit the source files and/or the notebook
to get what you want.
