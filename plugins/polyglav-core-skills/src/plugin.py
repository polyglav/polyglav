import importlib.util
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
_added = False
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
    _added = True
try:
    import skills as _skills
finally:
    if _added:
        sys.path.remove(str(SRC))

Skill = _skills.Skill


def register_services(services):
    services['skill_registry'] = _skills.SkillRegistry
    services['skills_section'] = _skills.skills_section


def register_commands(commands):
    chat = commands.chat_loop

    @commands.register(
        'skills', description='Manage skills', subcommands=[
            ('list', 'List skills'),
            ('show', 'Show a skill definition'),
            ('new', 'Create or override a skill (local)'),
            ('remove', 'Remove a skill'),
        ])
    def skill_cmd(arg=''):
        sr = chat.skills
        parts = arg.strip().split(maxsplit=1)
        action = parts[0] if parts else ''
        if not action or action == 'list':
            skills = sr.all()
            if not skills:
                print('  (no skills configured)')
                print(f'  Create one with /skills new <name>, or add a '
                      f'<name>.md file to {sr.local_dir}')
                return
            print(f'{len(skills)} skills:')
            for s in skills:
                desc = f' - {s.description}' if s.description else ''
                origin = f' ({sr.origin(s.name)})'
                print(f'  - {s.name}{desc}{origin}')
            return
        if action == 'show':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /skills show <name>')
                return
            s = sr.find(name)
            if s is None:
                print(f'Skill not found: {name}')
                return
            print(f'{s.name} ({sr.origin(s.name)})')
            if s.tags:
                print(f'  tags: {", ".join(s.tags)}')
            if s.content:
                print(s.content.rstrip())
            else:
                print('  (empty)')
            return
        if action == 'new':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /skills new <name>')
                return
            existing = sr.find(name)
            prev_origin = sr.origin(name)
            sr.put(Skill(name=name, content=''), scope='local')
            if existing is not None:
                print(f'Overrode skill: {name} (was {prev_origin}) - '
                      f'edit {sr.local_dir / (name + ".md")}')
            else:
                print(f'Created skill: {name} (local) - '
                      f'edit {sr.local_dir / (name + ".md")}')
            return
        if action == 'remove':
            name = parts[1].strip() if len(parts) > 1 else ''
            if not name:
                print('Usage: /skills remove <name>')
                return
            if sr.remove(name):
                print(f'Removed skill: {name} (local)')
            elif sr.origin(name) == 'plugin':
                print(f'{name} comes from a plugin - override it with '
                      '/skills new <name>, or edit the local skills dir, '
                      'instead of removing')
            else:
                print(f'No local skill to remove: {name}')
            return
        print('Usage: /skills [list|show <name>|new <name>|remove <name>]')
