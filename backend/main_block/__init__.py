"""The MAIN BLOCK: reasoning engine (Discovery.AI) + research engine (Dewey)
+ the door connecting them. Outside code imports `backend.main_block.interface`
only. Layout:

    main_block/
      interface.py        public API (the only import for clients)
      service.py api.py models.py store.py   the door: jobs, ask, HTTP routes
      reasoning_engine/   Discovery.AI  (its own interface.py)
      research_engine/    Dewey         (its own interface.py)
"""
