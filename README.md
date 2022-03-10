# PythOCR
## A python program to OCR videos

Adapted ~~(aka shamelessly stolen)~~ from the bash based video OCR YolOCR
https://git.clapity.eu/Id/YoloCR or https://bitbucket.org/YuriZero/yolocr/src/master/

It uses vapoursynth, ffmpeg and tesseract along with some python modules
Note: A fork of https://github.com/Lypheo/pythOCR originally from https://github.com/pocketsnizort/pythOCR

#### Notable differences of this fork by Lypheo are:
- It doesn’t depend on pyEnchant anymore, which has been discontinued and doesn’t have any 64 Windows builds.
- It allows the filter parameters in the vpy file to be set via command line arguments of the main script.
- It’s likely even more broken than the original because I can’t code for shit.

#### Changelog by pandamoon21:
11/03/2022:
- Cleaned code, updated deprecated functions, updated libs to 64 bit

TODO:
- Cross check the code with the original repo
- Fix path error
- Migrate to click or cloup from configargparse
- Make colored text
- Add more detailed docs
- ...

Requirements
============

Install 
- [python 3+](https://www.python.org/downloads/release) (Use the 32-bit version on Windows, because pyEnchant does not support Win64)
- [vapoursynth](https://github.com/vapoursynth/vapoursynth/releases)
- [tesseract](https://github.com/tesseract-ocr/tesseract/wiki/Downloads).
(Make sure to use the [official training data set](https://github.com/tesseract-ocr/tesseract/wiki/Data-Files). The one included in the Windows setup by UB Mannheim is faulty and needs to be replaced.)

##### Note: Python, ffmpeg and vspipe (vapoursynth) should be in the PATH

Install vapoursynth plugins:
- For Windows:
  1. Copy the content of dependecies/Win/vapoursynth_dep to your vapoursynth plugin folder
  2. Copy the content of dependecies/Win/python_dep to your python site-packages folder
- For Linux:
  - install [Vapoursynth-plugins](https://github.com/darealshinji/vapoursynth-plugins) (or use my containerized version of pythOCR)

Install (from pip) python prerequisites:
- Linux
`$pip3 install colorama configargparse pyspellchecker numpy opencv-python tqdm typing`
- Windows
`pip install colorama configargparse pyspellchecker numpy opencv-python tqdm typing`

Installation
============

clone this repository

Here, you're done.

How to use
==========


```
$python3 pythOCR.py --help
usage: pythOCR.py [-h] [-V] [-c CONFIG] [-l language] [-wd folder] [-o folder]
                  [-log level] [-ass style] [-rr path to regex-replace json]
                  [-hcr char,replace] [-sf format] [-m mode] [-vpy vpy_file]
                  [-T number] [-autosamesub number] [-samesub number] [-nsc]
                  [-t] [-d] [-tss path to tesseract binary]
                  [-vps path to vspipe binary] [-wdt number] [-hgt number]
                  [-cropy number] [-cropalty number] [-ss number] [-er number]
                  [-rs mode] [-wt number] [-bt number] [-dt number]
                  path [path ...]

Filters a video and extracts subtitles as srt or ass using YOLOCR

positional arguments:
  path                  Path to a video

optional arguments:
  -h, --help            show this help message and exit
  -V, --version         show program's version number and exit
  -c CONFIG, --config CONFIG
                        path to configuration file
  -l language, --lang language
                        Select the language of the subtitles (default: eng)
  -wd folder, --work-dir folder
                        Temporary stuff directory (default ./temp)
  -o folder, --output-dir folder
                        Output directory (default ./output)
  -log level, --log-level level
                        Set the logging level (default INFO)
  -ass style, --ass-style style
                        ASS style to use if sub-format is ass (default: Verdana 60)
  -rr path to regex-replace json, --regex-replace path to regex-replace json
                        List of regex/replace for automatic correction
  -hcr char,replace, --heuristic-char-replace char,replace
                        List of char/replace for heuristic correction
  -sf format, --sub-format format
                        Set the outputed subtitles format (default: srt)
  -m mode, --mode mode  Set the processing mode.
                        "filter" to only start the filtering jobs
                        "ocr" to process already filtered videos
                        "full" for filter + ocr (default: full)
  -vpy vpy_file, --vpy vpy_file
                        Vapoursynth file to use for filtering (default: extract_subs_v1.vpy)
  -T number, --threads number
                        Number of threads the script will use (default: automatic detection)
  -autosamesub number, --auto-same-sub-threshold number
                        Percentage of comparison to assert that two lines of subtitles
                        are automatically the same (default: 95)
  -samesub number, --same-sub-threshold number
                        Percentage of comparison to assert that two lines of subtitles
                        are the same (default: 80)
  -nsc, --no-spellcheck
                        Deactivate the function which tries to replace allegedly bad characters
                        using spellcheck (It will make the "heurist_char_replace"
                        option of the userconfig useless)
  -t, --timid           Activate timid mode
                        (It will ask for user input when some corrections are not automatically approved)
  -d, --delay           Delay correction after every video is processed
  -tss path to tesseract binary, --tesseract-path path to tesseract binary
                        The path to call tesseract (default: tesseract)
  -vps path to vspipe binary, --vapoursynth-path path to vspipe binary
                        The path to call vapoursynth (default: vspipe)
  -wdt number, --width number
                        Width of the box containing the subtitles in pixels
  -hgt number, --height number
                        Height of the box containing the subtitles in pixels
  -cropy number, --cropbox_y number
                        Height of the subtitle box relative to the bottom in pixels
  -cropalty number, --cropbox-alt_y number
                        Height of the alternative subtitle box (\an8) relative to the bottom in pixels.
                        -1 to disable (default)
  -ss number, --supersampling number
                        Supersampling factor, -1 to disable (default)
  -er number, --expand-ratio number
                        Expand/Inpand factor for supersampling
  -rs mode, --resampler mode
                        Scaling algorithm to use
  -wt number, --white-thresh number
                        Color threshold of the inner subtitles
  -bt number, --black-thresh number
                        Color threshold of the outer subtitles (the black border)
  -dt number, --detect-thresh number
                        General detection threshold
                        Lower values lead to more detected subs, more positive false
                        Higher values lead to subs difficult to detect
```
You need to specify the height (relative to the bottom) and the dimensions of the box the subtitles are contained in. So for example:
`python pythOCR.py /myVideos/vid01.mp4 -l eng -sf srt --width 120 --height 150 --cropbox_y 0`.

Developer for this repo:
<table>
  <tr>
    <td align="center"><a href="https://github.com/pandamoon21"><img src="https://avatars.githubusercontent.com/u/33972938?v=4?s=100" width="100px;" alt=""/><br /><sub><b>pandamoon21</b></sub></a><br /><a href="https://github.com/pandamoon21/pythOCR/commits?author=pandamoon21" title="Code">💻</a></td>
  </tr>
</table>
