
# Put this in project root as fix_credits_nav.py and run: python fix_credits_nav.py
import os, re, glob

templates_dir = "templates"
for filepath in glob.glob(f"{templates_dir}/*.html"):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    original = content
    
    # 1. UNIFY CREDIT to Nelson .T. Tactics
    content = re.sub(r'Naval T Tactics', 'Nelson .T. Tactics', content)
    content = re.sub(r'Nelson\.T\. Tactics', 'Nelson .T. Tactics', content)
    content = re.sub(r'Nelson.T. Tactics', 'Nelson .T. Tactics', content)
    content = re.sub(r'YOU.*Website Developer.*PRESERVED', 'Nelson .T. Tactics', content)
    # Fix footer junks
    content = content.replace('Fast • Responsive • Multi-user Ready', '')
    content = content.replace('ELEPHANT 8/7', '')
    content = content.replace('Built with ❤ by <span class="font-bold text-white">YOU</span>', 'Built with ❤ by <span class="font-bold text-white">Nelson .T. Tactics</span>')
    
    # 2. FIX NAV: /counselling -> /counselling-care
    content = content.replace('href="/counselling"', 'href="/counselling-care"')
    content = content.replace("href='/counselling'", "href='/counselling-care'")
    
    # 3. Make Faith Arcade glow premium
    content = content.replace('text-[#9b7cff] hover:text-[#facc15]', 'text-[#9b7cff] hover:text-[#facc15] faith-arcade-glow')
    content = content.replace('text-[#a78bfa]', 'text-[#a78bfa] faith-arcade-glow')
    
    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed {filepath}")

print("All credits unified to Nelson .T. Tactics, nav fixed, faith arcade glow class added")
