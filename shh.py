import pygetwindow as gw

for title in gw.getAllTitles():
    if title.strip():
        print(repr(title))