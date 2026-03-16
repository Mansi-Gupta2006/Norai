import urllib.request, urllib.parse, re
import sys

q = "arijit singh"
url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
html = urllib.request.urlopen(req, timeout=5).read().decode('utf-8')
match = re.search(r'"videoId":"([^"]+)"', html)
if match:
    print(match.group(1))
else:
    print("Not found")
