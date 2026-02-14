Commands to build the exe

pyinstaller --onefile --clean --noconsole --name VRF_Seva_Tool --hidden-import=gspread --hidden-import=google.oauth2 --add-data ".env;." --add-data "config.ini;." --add-data "credentials.json;." Run_front_end_Exe.py

pyinstaller --onefile --clean --noconsole --hidden-import=gspread --hidden-import=google.oauth2 --add-data ".env;." --add-data "config.ini;." --add-data "credentials.json;." AI_Summary.py

 pyinstaller --onefile --hidden-import=backports --hidden-import=backports.functools_lru_cache --hidden-import=pkg_resources.py2_warn --hidden-import=pkg_resources.extern --hidden-import=pkg_resources.extern.backports --hidden-import=pkg_resources.extern.backports.tarfile --collect-all gradio --collect-all transformers --collect-data gradio SevaAllocationMain.py

 pyinstaller --onefile --name=VRFReplacementMain --hidden-import=batch_allocator.vrf_indexer --hidden-import=batch_allocator.pinecone_utils --hidden-import=preprocessing.vrf_data --hidden-import=preprocessing.concat_participant_features --hidden-import=pinecone --hidden-import=llama_index.vector_stores.pinecone --hidden-import=llama_index.embeddings.openai --hidden-import=llama_index.llms.openai --hidden-import=llama_index.core --hidden-import=llama_index.core.schema --add-data="batch_allocator;batch_allocator" --add-data="Libraries;Libraries" --add-data="preprocessing;preprocessing" --add-data="config.ini;."  VRFReplacementMain.py
