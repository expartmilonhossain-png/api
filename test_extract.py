import json
from bs4 import BeautifulSoup
txt_p = open('pornhat_card.html', 'r', encoding='utf-16le').read()
soup_p = BeautifulSoup(txt_p, 'lxml')
print('PORNHAT:')
for a in soup_p.select('a'):
    cls = a.get('class', [])
    href = a.get('href', '')
    text = a.get_text(strip=True)
    print(f'[{cls}] {href} -> {text}')

txt_x = open('xhamster_card.html', 'r', encoding='utf-16le').read()
soup_x = BeautifulSoup(txt_x, 'lxml')
print('\nXHAMSTER:')
for a in soup_x.select('a'):
    cls = a.get('class', [])
    href = a.get('href', '')
    text = a.get_text(strip=True)
    print(f'[{cls}] {href} -> {text}')
