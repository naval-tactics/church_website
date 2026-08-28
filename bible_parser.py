"""
Bible Trivia Auto-Generator
Reads free KJV Bible text (Genesis to Revelation - 31,102 verses)
Generates Sunday School / Youth / Adult / Pastors levels
Exports bible_database.json for Flask app
"""

import re
import json
import random
from collections import defaultdict

BIBLE_TXT = "bible.txt" # put your free KJV text file here - format: "Genesis 1:1 In the beginning..."
OUTPUT_JSON = "bible_database.json"

# Books difficulty mapping
EASY_BOOKS = ["Genesis","Exodus","Psalms","Matthew","Mark","Luke","John","Acts","Jonah","Daniel","Ruth","Esther"]
MEDIUM_BOOKS = ["Joshua","Judges","1 Samuel","2 Samuel","1 Kings","2 Kings","Proverbs","Ecclesiastes","Matthew","Luke","Romans","1 Corinthians"]
HARD_BOOKS = ["Leviticus","Numbers","Deuteronomy","Job","Isaiah","Jeremiah","Ezekiel","Romans","Hebrews","Revelation"]
RARE_BOOKS = ["Leviticus","Numbers","Song of Solomon","Obadiah","Nahum","Habakkuk","Zephaniah","Haggai","Philemon","Jude","2 John","3 John"]

def load_bible():
    verses = []
    # Expected line: "Genesis 1:1 In the beginning God created..."
    pattern = r"^(.+?)\s+(\d+):(\d+)\s+(.+)$"
    try:
        with open(BIBLE_TXT, encoding='utf-8', errors='ignore') as f:
            for line in f:
                line=line.strip()
                if not line: continue
                m=re.match(pattern, line)
                if m:
                    book=m.group(1).strip()
                    chapter=m.group(2)
                    verse=m.group(3)
                    text=m.group(4)
                    verses.append({"book":book,"chapter":chapter,"verse":verse,"ref":f"{book} {chapter}:{verse}","text":text})
    except FileNotFoundError:
        print(f"[!] {BIBLE_TXT} not found. Using dummy sample to show structure. Put real KJV bible.txt to generate 31k verses.")
        # fallback dummy to test script
        verses=[
            {"book":"Genesis","chapter":"1","verse":"1","ref":"Genesis 1:1","text":"In the beginning God created the heaven and the earth."},
            {"book":"John","chapter":"3","verse":"16","ref":"John 3:16","text":"For God so loved the world..."},
        ]
    print(f"[+] Loaded {len(verses)} verses")
    return verses

def assign_level(book):
    if book in RARE_BOOKS: return "pastors"
    if book in HARD_BOOKS: return "adult"
    if book in EASY_BOOKS: return "sunday" if random.random()<0.6 else "youth"
    return "youth"

def make_question(v, all_verses):
    """Create 1 MCQ from a verse"""
    book=v["book"]
    # pick 3 random wrong verses as distractors
    distractors = random.sample([x for x in all_verses if x["book"]!=book], 3)

    # Question templates based on content
    templates = [
        (f"What book and chapter contains: \"{v['text'][:60]}...\"?", v["ref"], [d["ref"] for d in distractors]),
        (f"According to {v['ref']}, which book is this verse from?", v["book"], [d["book"] for d in distractors]),
        (f"Complete the verse {v['ref']}: \"{v['text'][:30]}...\"", v["text"][:80], [d["text"][:80] for d in distractors]),
        (f"In {v['book']} {v['chapter']}, what is the context of verse {v['verse']}?", f"Found in {book}", [f"Found in {d['book']}" for d in distractors]),
    ]
    q_text, correct, wrongs = random.choice(templates)

    options = wrongs + [correct]
    random.shuffle(options)
    answer_index = options.index(correct)

    return {
        "q": q_text,
        "options": options,
        "answer": answer_index,
        "ref": v["ref"],
        "book": book,
        "verse_text": v["text"]
    }

def parse_and_export():
    verses = load_bible()
    database = {"sunday":[],"youth":[],"adult":[],"pastors":[]}
    id_counters = defaultdict(int)

    for v in verses:
        level = assign_level(v["book"])
        # Simple narratives for Sunday
        if level=="sunday" and len(v["text"].split())>20: continue # keep short for kids
        if level=="pastors" and v["book"] not in RARE_BOOKS+HARD_BOOKS and random.random()<0.8: continue

        q = make_question(v, verses)
        id_counters[level]+=1
        q["id"]=id_counters[level]

        # Flagging logic
        q["difficulty"]=level
        q["flag"]="simple" if level=="sunday" else "theological" if level in ["adult","pastors"] else "general"

        database[level].append(q)

        # Limit for demo - remove this when you have full bible.txt
        if id_counters[level]>=250: # 250 per level = 1000 total
            if all(c>=150 for c in id_counters.values()):
                pass # continue until we hit 1000

    # Trim to 200 per level for clean file (800 total covering Genesis-Revelation)
    for lvl in database:
        database[lvl]=database[lvl][:200]

    with open(OUTPUT_JSON,'w', encoding='utf-8') as out:
        json.dump(database, out, indent=2, ensure_ascii=False)

    print(f"[+] Exported {OUTPUT_JSON}")
    for lvl in database:
        print(f" - {lvl}: {len(database[lvl])} questions")
    print(f"\n[OK] Now in Flask: json.load(open('bible_database.json'))")

if __name__=="__main__":
    parse_and_export()