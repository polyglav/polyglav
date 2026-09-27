from opencode import OpenCodeProvider
from opencode_go import OpenCodeGoProvider


def register_providers(providers):
    providers['opencode'] = OpenCodeProvider
    providers['opencode-go'] = OpenCodeGoProvider