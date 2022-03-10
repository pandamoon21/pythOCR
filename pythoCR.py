from argparse import RawTextHelpFormatter
import configargparse
import difflib
import json
import logging
import math
import multiprocessing
import os
import pdb
import re
import shlex
import shutil
import subprocess

from itertools import product
from colorama import init, Fore, Style
from multiprocessing.dummy import Pool as ThreadPool 
from pathlib import Path, PurePath
from spellchecker import SpellChecker
from tqdm import tqdm
from utils import Logger

VERSION = "2.05"

last_frame = 0
video_fps = 0

# TODO: Use subedit
def which(*executables):
    return next(iter(
        sorted(
            (Path(x) for x in (shutil.which(x) for x in executables) if x),
            key=lambda x: os.environ["PATH"].split(os.pathsep).index(str(x.parent)),
        )
    ), None)

subtitleedit = which("subtitleedit")


spell = SpellChecker()
def is_word(word):
    return spell.known([word]) == {word}


def show_diff(seqm):
    """
    Unify operations between two compared strings
    seqm is a difflib.SequenceMatcher instance whose a & b are strings
    """
    output= []
    for opcode, a0, a1, b0, b1 in seqm.get_opcodes():
        if opcode == 'equal':
            output.append(seqm.a[a0:a1])
        elif opcode == 'insert':
            output.append(Fore.RED + Style.BRIGHT + seqm.b[b0:b1] + Style.RESET_ALL)
        elif opcode == 'delete':
            continue
        elif opcode == 'replace':
            output.append(Fore.RED + Style.BRIGHT + seqm.b[b0:b1] + Style.RESET_ALL)
    return ''.join(output)


def analyse_word_count(sub_data, language):
    word_count = dict()
    for idx in range(0, len(sub_data)):
        for word in re.findall(r"\w+", strip_tags(sub_data[idx][0]), flags=re.UNICODE):
            if is_word(word):
                try:
                    word_count[word] += 1
                except KeyError:
                    word_count[word] = 1
    return word_count


def filler(word, from_char, to_char):
    options = [(c,) if c != from_char else (from_char, to_char) for c in word]
    return (''.join(o) for o in product(*options))


def user_input_replace_confirm(word, substitutes, fullstring):
    displaystring = fullstring.split(word, 1)
    displaystring = displaystring[0] + Fore.RED + Style.BRIGHT + word + Style.RESET_ALL + displaystring[1]
    msg = f" + Dialogue: \"{strip_tags(displaystring)}\"\n"
    msg += " + Bad word found, please select a substitute or enter [s] to skip:\n"
    msg += ", ".join([
        ("\"{}\"[" + Fore.BLUE + Style.BRIGHT + "{}" + Style.RESET_ALL + "]").format(
            show_diff(difflib.SequenceMatcher(a=word, b=substitute[0])), idx + 1
            ) for idx, substitute in enumerate(substitutes)
    ])
    while True:
        log.info(msg)
        user_input = input()
        if user_input.lower() == "s":
            return word
        elif user_input == "":
            return substitutes[0][0]
        else:
            try: 
                idx = int(user_input)
            except ValueError:
                log.warn(" - Please enter a valid number (not a number)")
                continue
            if idx >= 1 and idx <= len(substitutes):
                return substitutes[idx - 1][0]
            else:
                log.warn(" - Please enter a valid number (out of bound)")
                continue


def extreme_try_word_without_char(word, fullstring, chars_to_try_to_replace, word_count):
    if is_word(word):
        return word
    else:
        substitutes = {word}
        for char, replacement in chars_to_try_to_replace:
            raw_subst = [filler(word, char, replacement) for word in substitutes]
            substitutes = set([subst for sublist in raw_subst for subst in sublist])
            
        # Get a list of acceptable substitutes with their corresponding distance
        substitutes = [
            (
                substitute,
                difflib.SequenceMatcher(None, word, substitute).ratio()
            ) for substitute in list(set(substitutes)) if is_word(substitute)
        ]
        if len(substitutes) > 0:
            log.debug(" + Heuristic - Found bad word \"{}\", possibles substitutes are \"{}\"".format(
                word,
                str(substitutes)
            ))
            if args.timid:
                return user_input_replace_confirm(word, substitutes, fullstring)
            else:
                chosen_subst = sorted(
                    substitutes,
                    key=lambda substitute: 100 * word_count.get(substitute[0], 0) * substitute[1],
                    reverse=True
                    )[0]
                log.debug(" + Heuristic - Choose most likely substitute: %s [%d%%]".format(chosen_subst))  # TODO: Ganti jadi f string/format
            return chosen_subst[0]
        else:
            log.debug(f" + Heuristic - Found bad word \"{word}\", no substitutes acceptable found.")
    return word


def extreme_try_string_without_char(string, chars_to_try_to_replace, word_count):
    for word in re.findall(
        r"\w+[" + re.escape("".join([char[0] for char in chars_to_try_to_replace])) + r"]\w+",
        string,
        flags=re.UNICODE
    ):
        substitute = extreme_try_word_without_char(
            word, string, chars_to_try_to_replace, word_count
            )
        if substitute != word:
            re.sub(
                r"(\W)" + re.escape(word) + r"(\W)", "\\1" + substitute + "\\2",
                string,
                flags=re.UNICODE
            )
    return string


def extreme_try_subs_without_char(sub_data, chars_to_try_to_replace, language, word_count):
    for idx in range(0, len(sub_data)):
        sub_data[idx] = (
            extreme_try_string_without_char(
                sub_data[idx][0],
                chars_to_try_to_replace,
                word_count
            ),
            sub_data[idx][1]
        )
    return sub_data


def new_ocr_image(arg_tuple):
    scene, language, pbar = arg_tuple
    img_path = scene[2]
    result_base = PurePath(img_path).suffix[0]
    
    tess_cmd = [args.tesseract_path, img_path, "stdout", "-l", language, "--psm", "6", "hocr"]
    html_content = subprocess.check_output(
        tess_cmd,
        stderr=subprocess.DEVNULL
    ).decode('utf-8')
        
    # Convert to text only
    text = re.sub(r"<(?!/?em)[^>]+>", "", html_content)
    text = text.strip().replace(
        "</em> <em>", " ").replace(
        "&#39;", "'").replace(
        "&quot;", "\"").replace(
        "&amp;", "&").replace(
        "&gt;", ">").replace(
        "&lt;", "<")
    text = re.sub(r"<(/?)em>", "<\\1i>", text)
    text = '\n'.join([x.strip() for x in text.splitlines() if x.strip()])
    text = re.sub(r"</i>(?:\r\n|\n)<i>", "\n", text)
    
    pbar.update(1)
    return text, (scene[0], scene[1])


# Fix time issues by someonelike-u
def truncateDecimalNumber(number, decimals=0):
    """
    Returns a value truncated to a specific number of decimal places.
    https://kodify.net/python/math/truncate-decimals/
    """
    if not isinstance(decimals, int):
        raise TypeError("decimal places must be an integer.")
    elif decimals < 0:
        raise ValueError("decimal places has to be 0 or more.")
    elif decimals == 0:
        return math.trunc(number)

    factor = 10.0 ** decimals
    return math.trunc(number * factor) / factor


# Refix the time for recent software
def sec_to_time(secs):
    hours = secs / 3600
    minutes = (secs % 3600) / 60
    secs = secs % 60
    # Truncate the decimal number, no rounding to avoid time issues (like for time plan) 
    secs = truncateDecimalNumber(secs % 60, 2)
    # Get always 2 digits before the comma and 2 digits after the comma
    return "%02d:%02d:%05.2f" % (hours, minutes, secs)


def convert_to_srt(sub_data, mp4_path):
    """
    First, we need to handle the case where default and
    alternative subs are displayed at the same time
    """
    
    idx = 0
    while idx < len(sub_data) - 1:
        if int(sub_data[idx][1][1]) >= int(sub_data[idx + 1][1][0]):
            if "<font color=\"#ffff00\">" in sub_data[idx][0]:
                alt_line = sub_data[idx][0]
                def_line = sub_data[idx + 1][0]
            else:
                alt_line = sub_data[idx + 1][0]
                def_line = sub_data[idx][0]
                
            if int(sub_data[idx][1][1]) < int(sub_data[idx + 1][1][1]):
                # Case where first line shorter than the second
                bound1 = sub_data[idx + 1][1][0]
                bound2 = sub_data[idx][1][1]
                sub_data.insert(
                    idx + 2,
                    (sub_data[idx + 1][0], (bound2, sub_data[idx + 1][1][1]))
                )
                sub_data[idx] = (
                    sub_data[idx][0],
                    (sub_data[idx][1][0], bound1)
                )
                sub_data[idx + 1] = ("{}\n{}".format(
                    (alt_line, def_line),
                    (bound1, bound2)
                ))
            elif int(sub_data[idx][1][1]) > int(sub_data[idx + 1][1][1]):
                # Case where first line longer than the second
                bound1 = sub_data[idx + 1][1][0]
                bound2 = sub_data[idx + 1][1][1]
                sub_data.insert(
                    idx + 2,
                    (sub_data[idx][0], (bound2, sub_data[idx][1][1]))
                )
                sub_data[idx] = (
                    sub_data[idx][0],
                    (sub_data[idx][1][0], bound1)
                )
                sub_data[idx + 1] = ("{}\n{}".format(
                    (alt_line, def_line),
                    (bound1, bound2)
                ))
            else:
                # Case where the lines end at the same time
                sub_data[idx] = (
                    sub_data[idx][0],
                    (sub_data[idx][1][0], sub_data[idx + 1][1][0])
                )
                sub_data[idx + 1] = ("{}\n{}".format(
                    (alt_line, def_line),
                    (sub_data[idx + 1][1][0], sub_data[idx + 1][1][1])
                ))
            idx += 1
        idx += 1

    with open(f"{PurePath(mp4_path).suffix[0]}.srt", "w", encoding="utf8") as ofile:
        idx = 1
        for data in sub_data:
            if len(data[0]) > 0:
                text = f"{idx}\n"
                text += ("{} --> {}\n".format(
                    sec_to_time(float(data[1][0]) / video_fps),
                    sec_to_time((float(data[1][1]) / video_fps)))
                ).replace('.', ',')
                text += data[0]
                text += "\n\n"
                ofile.write(text)
                idx += 1


# TODO: Use subtitleedit for converting to ass
def convert_to_ass(sub_data, mp4_path):
    with open(f"{PurePath(mp4_path).suffix[0]}.ass", "w", encoding="utf8") as ofile:
        ofile.write(u'[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\n'
                    u'PlayResX: 1920\nPlayResY: 1080\n\n')
        ofile.write(u'[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour,'
                    u' SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, '
                    u'StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
                    u'Alignment, MarginL, MarginR, MarginV, '
                    u'Encoding\n')
        ofile.write(args.ass_style)
        ofile.write(u'\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV,'
                    u' Effect, Text\n')
        for data in sub_data:
            if len(data[0]) > 0:
                starttime = sec_to_time(float(data[1][0]) / video_fps)
                endtime = sec_to_time((float(data[1][1]) / video_fps))
                text = data[0].replace(
                    "\n", " ").replace(
                    "<i>", "{\\i1}").replace(
                    "</i>", "{\\i0}").replace(
                    "<font color=\"#ffff00\">", "{\\an8}").replace(
                    "</font>", "{\\an}").replace(
                    "}{", "")
                ofile.write(u'Dialogue: 0,'+starttime+','+endtime+',Default,,0,0,0,,'+text+u'\n')


def score_lines(line_a, line_b, language):
    score_a = sum([
        1 for word in re.findall(r"\w+", strip_tags(line_a), re.UNICODE) if is_word(word)
    ])
    score_b = sum([
        1 for word in re.findall(r"\w+", strip_tags(line_b), re.UNICODE) if is_word(word)
    ])
    if score_a > score_b:
        return line_a
    else:
        return line_b


def strip_tags(string_):
    string_ = string_.replace(
        '\n', ' ').replace(
        '<i>', '').replace(
        '</i>', '').replace(
        '<font color="#ffff00">', '').replace(
        '</font>', '')
    return string_


def check_sub_data(sub_data):
    log.debug(" + Correcting - Removing empty lines")
    sub_data = [data for data in sub_data if len(data[0]) > 0]
    
    for idx in range(len(sub_data)):
        text = sub_data[idx][0]
        for regex in args.regex_replace:
            text = re.sub(regex[0], regex[1], text)
        sub_data[idx] = (text, sub_data[idx][1])
    
    if not args.no_spellcheck and len(args.heurist_char_replace) > 0:
        word_count = analyse_word_count(sub_data, args.lang)
        
        log.debug(" + Correcting - Deleting heuristicly unwanted chars")
        sub_data = extreme_try_subs_without_char(
            sub_data, args.heurist_char_replace, args.lang, word_count
        )

    log.debug(" + Correcting - Adding trailing frame")
    for idx in range(len(sub_data)):
        sub_data[idx] = (
            sub_data[idx][0],
            (sub_data[idx][1][0], str(int(sub_data[idx][1][1]) + 1))
        )
        
    log.debug(" + Correcting - Merging identical consecutive lines")
    idx = 0
    while idx < len(sub_data) - 1:
        if int(sub_data[idx][1][1]) >= int(sub_data[idx + 1][1][0]):
            score = 100. * difflib.SequenceMatcher(
                None,
                strip_tags(sub_data[idx][0]),
                strip_tags(sub_data[idx + 1][0])
            ).ratio()
            a = sub_data[idx][0].replace('\n', "")
            b = sub_data[idx + 1][0].replace('\n', "")
            b = show_diff(difflib.SequenceMatcher(a=a, b=b))
            msg = f"{a}\n{b}\nCompare score of {score:.2f}"
            if score >= args.auto_same_sub_threshold:
                log.debug(f"\n{msg} - Approved (automatically - higher threshold)")
                sub_data[idx] = (
                    score_lines(
                        sub_data[idx][0],
                        sub_data[idx + 1][0],
                        args.lang
                    ),
                    (sub_data[idx][1][0], sub_data[idx + 1][1][1])
                )
                del sub_data[idx + 1]
            elif score >= args.same_sub_threshold:
                if args.timid:
                    print(msg)
                    user_input = input(" + Approve similarity? (Y/n)").lower()
                    log.debug(f" + User_input is {user_input}")
                    if user_input in ('y', ''):
                        log.info(" + Change approved (user input)")
                        sub_data[idx] = (
                            score_lines(
                                sub_data[idx][0],
                                sub_data[idx + 1][0],
                                args.lang
                            ),
                            (sub_data[idx][1][0], sub_data[idx + 1][1][1])
                        )
                        del sub_data[idx + 1]
                elif not args.timid:
                    log.debug(f"\n{msg} - Approved (automatically)")
                    sub_data[idx] = (
                        score_lines(
                            sub_data[idx][0],
                            sub_data[idx + 1][0],
                            args.lang
                        ),
                        (sub_data[idx][1][0], sub_data[idx + 1][1][1])
                    )
                    del sub_data[idx + 1]
        idx += 1
        
    return sub_data


def new_filter_only(path, outputdir):
    log.info(f" + Starting mode filter for file {path}")
    
    params = " --arg ".join([
        "Source=\"" + path.replace("\\", "\\\\") + "\"",
        "OutputDir=" + outputdir,
        "width=" + str(args.width),
        "height=" + str(args.height),
        "CropBox_y=" + str(args.CropBox_y),
        "CropBoxAlt_y=" + str(args.CropBoxAlt_y),
        "Supersampling=" + str(args.Supersampling),
        "ExpandRatio=" + str(args.ExpandRatio),
        "Resampler=" + str(args.Resampler),
        "WhiteThresh=" + str(args.WhiteThresh),
        "BlackThresh=" + str(args.BlackThresh),
        "DetectionThresh=" + str(args.DetectionThresh)
        ])
    
    vscmd = f"'{args.vapoursynth_path}' -c y4m -p --arg " + params + f" '{args.vpy}' -"
    log.debug(f" + Command used: {vscmd}")
    
    with open(os.devnull, 'w') as fnull:
        subprocess.call(shlex.split(vscmd), stdout=fnull)
    
    if Path(path + ".ffindex").is_file():
        Path(path + ".ffindex").unlink(missing_ok=True)


def get_scenes_from_scene_data(scene_data, last_frame, base_dir):
    scene_bounds = []
    scene_bounds = re.findall(
        r"(\d+),(\d),(\d),\"([^\"]*)\"", "\n".join(scene_data.split("\n")[1:])
    )
    scene_bounds = sorted(scene_bounds, key=lambda scene_bound: scene_bound[0])
    
    scenes = []
    start_frame = None
    start_img_path = None
    for idx, scene_bond in enumerate(scene_bounds):
        frame = int(scene_bond[0])
        is_start = int(scene_bond[1])
        is_end = int(scene_bond[2])
        img_path = scene_bond[3]
        img_path = os.path.join(base_dir, img_path)
        if idx == 0 and not is_start and is_end:
            # Case where scenechange missed first scene ??? (has happened)
            pass
        elif is_start and is_end: 
            # Case where the scene is one frame long (should not happen too often)
            scenes.append((frame, frame, img_path))
        elif is_start:
            start_frame = frame
            start_img_path = img_path
        elif is_end and start_frame and start_img_path:
            scenes.append((start_frame, frame, start_img_path))
            start_frame = None
            start_img_path = None
        else:
            # Should not get here often, but still
            pass
    if start_frame and start_img_path:
        scenes.append((start_frame, last_frame, start_img_path))
    return scenes


def ocr_scenes(scenes):
    log.info(" + OCRing images...")
    pool = ThreadPool(args.threads)
    pbar = tqdm(total=len(scenes), mininterval=1)
    scenes = pool.map(new_ocr_image, [(scene, args.lang, pbar) for scene in scenes])
    pool.close()
    pool.join()
    pbar.close()
    return scenes


def ocr_one_screenlog(screenlog_dir):
    log.info(f" + OCR - Processing directory {screenlog_dir}")

    with open(Path(screenlog_dir).joinpath("SceneChanges.csv"), "r") as ifile:
        video_data, scene_data = ifile.read().split("[Scene Informations]\n", 1)
        
    global video_fps
    global last_frame
    
    video_data_match = re.findall(
        r"\[Video Informations\]\nfps=(\d+\.\d+)\nframe_count=(\d+)",
        video_data
    )[0]
    video_fps = float(video_data_match[0])
    last_frame = int(video_data_match[1]) - 1
    
    log.debug(f" + Video framerate is: {str(video_fps)}")
    log.debug(f" + Last frame is: {last_frame}")
    
    scenes = get_scenes_from_scene_data(scene_data, last_frame, screenlog_dir)
    return ocr_scenes(scenes)


def new_ocr_only(input_root_dir):
    filename = input_root_dir.split("\\")[-1]
    log.debug(f" + filename: {filename}")
    
    input_root_dir = input_root_dir.replace(filename, "")
    screenlog_path = Path(input_root_dir).joinpath("output", filename, "default", "SceneChanges.csv")    # TODO: Fix this path error
    
    if not os.path.isfile(screenlog_path):
        log.error(f" - No screenlog found in dir \"{screenlog_path}\", aborting.")
        return (None,)
    
    alt_exists = Path(Path(input_root_dir).joinpath("alt", "SceneChanges.csv")).is_file()
    log.debug(" + Alternative Screenlog found." if alt_exists else "No alternative Screenlog found.")
    
    default_path = Path(input_root_dir).joinpath("output", filename, "default")
    one_screenlog = ocr_one_screenlog(default_path)
    if alt_exists:
        alt_path = Path(input_root_dir).joinpath("alt")
        alts_screenlog = [(
            "<font color=\"#ffff00\">" + text + "</font>", time
        ) for (text, time) in ocr_one_screenlog(alt_path)]
        
        return one_screenlog, alts_screenlog
    else:
        return one_screenlog,


def post_process_subs(subsdata, outputdir, path):
    # Merging everything and converting
    log.info(" + Correcting subtitles...") 
    sub_data = check_sub_data(subsdata[0])
    if len(subsdata) == 2:
        sub_data += check_sub_data(subsdata[1])
    log.info(" + Converting to subtitle file...") 
    sub_data = sorted(sub_data, key=lambda file: int(file[1][0]))
    {
        "ass": convert_to_ass,
        "srt": convert_to_srt
    }[args.sub_format](
        sub_data, Path(outputdir).joinpath(PurePath(path).name)
        )


def type_regex_replace(string):
    try:
        with open(string, "r", encoding="utf8") as inputfile:
            json_str = inputfile.read()
        json_str = json.loads(json_str)
        return [(re.compile(entry["regex"]), entry["replace"]) for entry in json_str]
    except IOError:
        raise configargparse.ArgumentTypeError(f"- File \"{string}\" not found")


def type_heurist_char_replace(string):
    try:
        with open(string, "r", encoding="utf8") as inputfile:
            json_str = inputfile.read()
        json_str = json.loads(json_str)
        return [(entry["char"], entry["replace"]) for entry in json_str]
    except IOError:
        raise configargparse.ArgumentTypeError(f"- File \"{string}\" not found")


def new_do_full(path):
    new_filter_only(path, args.workdir)
    path_ = Path(args.workdir).joinpath(PurePath(path).name)
    subsdata = new_ocr_only(path_)
    shutil.rmtree(path_, ignore_errors=True)
    return subsdata


if __name__ == "__main__":
    
    default_ass_style = "Style: Default,Verdana,55.5,&H00FFFFFF,&H000000FF,&H00282828,&H00000000,-1,0,0,0,100.2,100,0,0,1,3.75,0,2,0,0,79,1"
    
    args_ = configargparse.ArgumentParser(
        description="Filters a video and extracts subtitles as srt or ass using YOLOCR",
        formatter_class=RawTextHelpFormatter
        )
    args_.add_argument("-V", "--version", action="version", version=f"PythOCR {VERSION}")
    args_.add_argument("-c", "--config", is_config_file=True, help='path to configuration file')
    args_.add_argument("path", nargs='+', help="Path to a video")
    args_.add_argument("-l", "--lang", dest="lang", metavar="language",
                       choices=["eng", "fra", "ind"], type=str.lower, default="eng",
                       help="Select the language of the subtitles (default: eng)")
    args_.add_argument("-wd", "--work-dir", dest="workdir", metavar="folder", type=str, default="temp",
                       help="Temporary stuff directory (default ./temp)")
    args_.add_argument("-o", "--output-dir", dest="outputdir", metavar="folder", type=str, default="output",
                       help="Output directory (default ./output)")
    args_.add_argument("-log", "--log-level", dest="log_level", metavar="level", type=str.lower,
                       choices=["INFO", "DEBUG"], default="INFO",
                       help='Set the logging level (default INFO)')
    args_.add_argument("-ass", "--ass-style", dest="ass_style", metavar="style",
                       type=str, default=default_ass_style,
                       help="ASS style to use if sub-format is ass (default: Verdana 60)")
    args_.add_argument("-rr", "--regex-replace", dest="regex_replace", metavar="path to regex-replace json",
                       type=type_regex_replace, default=[],
                       help="List of regex/replace for automatic correction")
    args_.add_argument("-hcr", "--heuristic-char-replace", dest="heurist_char_replace", metavar="char,replace",
                       type=type_heurist_char_replace, default=[],
                       help="List of char/replace for heuristic correction")
    args_.add_argument("-sf", "--sub-format", dest="sub_format", metavar="format",
                       choices=["srt", "ass"], default="srt", type=str.lower,
                       help="Set the outputed subtitles format (default: srt)")
    args_.add_argument("-m", "--mode", dest="mode", metavar="mode",
                       choices=["full", "filter", "ocr"], default="full", type=str.lower,
                       help="Set the processing mode."
                            "\n\"filter\" to only start the filtering jobs"
                            "\n\"ocr\" to process already filtered videos"
                            "\n\"full\" for filter + ocr (default: full)")
    args_.add_argument("-vpy", "--vpy", dest="vpy", metavar="vpy_file", type=str, default="extract_subs_v1.vpy",
                       help="Vapoursynth file to use for filtering (default: extract_subs_v1.vpy)")
    args_.add_argument("-T", "--threads", dest="threads", metavar="number",
                       type=int, default=multiprocessing.cpu_count(),
                       help="Number of threads the script will use (default: automatic detection)")
    args_.add_argument("-autosamesub", "--auto-same-sub-threshold", dest="auto_same_sub_threshold",
                       metavar="number", type=float, default=95.,
                       help="Percentage of comparison to assert that two lines of subtitles"
                            "\nare automatically the same (default: 95)")
    args_.add_argument("-samesub", "--same-sub-threshold", dest="same_sub_threshold",
                       metavar="number", type=float, default=80.,
                       help="Percentage of comparison to assert that two lines of subtitles"
                            "\nare the same (default: 80)")
    args_.add_argument("-nsc", "--no-spellcheck", dest="no_spellcheck", action="store_true",
                       help="Deactivate the function which tries to replace allegedly bad characters"
                       "\nusing spellcheck (It will make the \"heurist_char_replace\""
                        "\noption of the userconfig useless)")
    args_.add_argument("-t", "--timid", dest="timid", action="store_true",
                       help="Activate timid mode"
                            "\n(It will ask for user input when some corrections are not automatically approved)")
    args_.add_argument("-d", "--delay", dest="delay", action="store_true",
                       help="Delay correction after every video is processed")
    args_.add_argument("-tss", "--tesseract-path", dest="tesseract_path", metavar="path to tesseract binary",
                       type=str, default="tesseract",
                       help="The path to call tesseract (default: tesseract)")
    args_.add_argument("-vps", "--vapoursynth-path", dest="vapoursynth_path", metavar="path to vspipe binary",
                       type=str, default="vspipe",
                       help="The path to call vapoursynth (default: vspipe)")
    args_.add_argument("-wdt", "--width", dest="width", metavar="number",
                       help="Width of the box containing the subtitles in pixels")
    args_.add_argument("-hgt", "--height", dest="height", metavar="number",
                       help="Height of the box containing the subtitles in pixels")
    args_.add_argument("-cropy", "--cropbox_y", dest="CropBox_y", metavar="number", default=0,
                       help="Height of the subtitle box relative to the bottom in pixels")
    args_.add_argument("-cropalty", "--cropbox-alt_y", dest="CropBoxAlt_y", metavar="number", default=-1,
                       help="Height of the alternative subtitle box (\\an8) relative to the bottom in pixels."
                            "\n-1 to disable (default)")
    args_.add_argument("-ss", "--supersampling", dest="Supersampling", metavar="number", default=-1,
                       help="Supersampling factor, -1 to disable (default)")
    args_.add_argument("-er", "--expand-ratio", dest="ExpandRatio", metavar="number", default=1,
                       help="Expand/Inpand factor for supersampling")
    args_.add_argument("-rs", "--resampler", dest="Resampler", metavar="mode",
                       choices=["sinc", "nnedi3", "waifu2x"], default="sinc",
                       help="Scaling algorithm to use")
    args_.add_argument("-wt", "--white-thresh", dest="WhiteThresh", metavar="number", default=230,
                       help="Color threshold of the inner subtitles")
    args_.add_argument("-bt", "--black-thresh", dest="BlackThresh", metavar="number", default=80,
                       help="Color threshold of the outer subtitles (the black border)")
    args_.add_argument("-dt", "--detect-thresh", dest="DetectionThresh", metavar="number", default=0.03,
                       help="General detection threshold"
                       "\nLower values lead to more detected subs, more positive false"
                       "\nHigher values lead to subs difficult to detect")
    
    args = args_.parse_args()
    
    """
    Folder:
        Folder where to place the produced results (sub-images)
    Dimension:
        Size in width and height of the CropBox delimiting the OCR subtitles.
    Height:
        Height of the CropBox delimiting the OCR subtitles.
    HeightAlt:
        Height of CropBox Alternative, useful for OCR of indications.
        Double the processing time. Set to -1 to disable.
    Supersampling:
        Supersampling factor (multiplication of video resolution).
        Set to -1 to calculate the factor automatically.
    Expand Ratio:
        EXPERIMENTAL! Expand/Inpand factor.
        A value of 1 is suitable for automatic Supersampling (1080p).
        Typical value calculation: ExpandRatio="FinalResolution"/1080.
    Mode:
        'sinc' (2 taps, faster),
        'nnedi3' (slower) or 'waifu2x' (much slower),
        controls the Upscale method.
    Treshold:
        Threshold delimiting the subtitles.
        This value corresponds to the minimum interior brightness (Inline).
    Treshold2:
        Threshold delimiting the subtitles.
        This value corresponds to the maximum brightness of the exterior (Outline).
    Tresh:
        A threshold that is too low increases the number of false positives,
        a threshold that is too high does not detect all the subtitles.
    """
    
    loglevel = args.log_level
    logging.basicConfig(level=logging.DEBUG if loglevel == "debug" else logging.INFO)
    log = Logger.getLogger(level=logging.DEBUG if loglevel == "debug" else logging.INFO)
    
    if not Path(args.outputdir).is_dir():
        log.debug(" + The output directory not exist, making a new one...")
        Path(args.outputdir).mkdir(parents=True, exist_ok=True)

    log.debug(f" + Logger level set to: {args.log_level}")
    log.debug(f" + Working with threads: {args.threads}")
    log.debug(f" + Work directory set to: {args.workdir}")
    log.debug(f" + Output directory set to: {args.outputdir}")
    log.debug(" + regex_replace list of {} is: {}".format(
        len(args.regex_replace),
        '; '.join([x for x in args.regex_replace])
    ))
    log.debug(" + heurist_char_replace list of {} is: {}".format(
        len(args.heurist_char_replace),
        '; '.join([x for x in args.heurist_char_replace])
    ))
    
    # colorama
    init()
    
    if (args.mode == "full" or "filter-only") and args.vpy is None:
        log.exit(" - Please provide a vpy file for filter mode to work.")
    
    log.debug(f" + Creating directory at path {args.workdir}")

    if not Path(args.workdir).is_dir():
        Path(args.workdir).mkdir(parents=True, exist_ok=True)
    
    files_to_process = []
    media_ext = {".avi", ".mp4", ".mkv", ".ts"}
    for path in args.path:
        if Path(path).is_file():
            if PurePath(path).suffix[1] in media_ext:
                files_to_process.append(path)
            else:
                log.exit(f" - {path} is not a video file!")
        elif Path(path).is_dir() and args.mode != "ocr":
            for file in Path(path).iterdir():
                if PurePath(file).suffix[1] in media_ext:
                    files_to_process.append(PurePath(path).joinpath(file))
        elif Path(path).is_dir() and args.mode == "ocr":        # TODO: STILL ERROR
            if ("." + path.split(".")[-1]) in media_ext:
                files_to_process.append(path)
    
    log.debug(f" + Files to process:\n{files_to_process}")
    log.info(f" + Mode used: {args.mode}")
    
    job = {
        "full": new_do_full,
        "ocr": new_ocr_only,
        "filter": new_filter_only
        }[args.mode]
                    
    subsdatalist = []
    for idx, file in enumerate(files_to_process):
        log.info("Processing {}, file {} of {}".format(
            PurePath(file).name,
            idx + 1,
            len(files_to_process)
        ))
        subsdata = job(file, args.outputdir) if args.mode == "filter" else job(file)
        if not args.mode == "filter" and not args.delay:
            post_process_subs(subsdata, args.outputdir, file)
        else:
            subsdatalist.append((subsdata, file))
             
    if not args.mode == "filter":
        for subsdata, path in subsdatalist:
            post_process_subs(subsdata, args.outputdir, path)
        
