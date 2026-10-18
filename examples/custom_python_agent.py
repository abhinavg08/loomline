"""Independent custom agent using only public SDK and shared NVIDIA gateway."""
from .framework_worker import main
if __name__=='__main__':
    import sys
    sys.argv.insert(1,'custom')
    main()
