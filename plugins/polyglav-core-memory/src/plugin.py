def register_commands(commands):
    chat = commands.chat_loop

    @commands.register(
        'memorize',
        description='Summarize the run into role, team, or job memory',
        subcommands=[
            ('', 'Memorize the active run into the active role memory'),
            ('<role|team|job> [name]', 'Memorize into a named scope'),
        ])
    def memorize_cmd(arg=''):
        parts = arg.strip().split(maxsplit=1)
        scope = parts[0] if parts else 'role'
        name = parts[1].strip() if len(parts) > 1 else ''
        print(chat.memorize(scope, name))
