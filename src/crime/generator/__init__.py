"""Build treated datasets and space-time cubes."""


def __getattr__(name):
    if name in ('generate_dataset', 'load_dataset', 'generate_cube'):
        from crime.generator import api
        return getattr(api, name)
    raise AttributeError(name)


__all__ = ['generate_dataset', 'load_dataset', 'generate_cube']
