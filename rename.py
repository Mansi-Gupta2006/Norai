import os

directories = ['d:/akira']
extensions = ['.py', '.html', '.md']

for root, _, files in os.walk('d:/akira'):
    for file in files:
        if any(file.endswith(ext) for ext in extensions) and file != 'rename.py':
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            new_content = content.replace('AKIRA', 'NORAI')
            new_content = new_content.replace('Akira', 'Norai')
            new_content = new_content.replace('akira', 'norai')

            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"Updated {filepath}")
