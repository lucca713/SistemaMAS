from langchain_community.document_loaders import WebBaseLoader
from langchain_community.document_loaders import TextLoader
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import Chroma
import json
import os


def load_documents():
    """
    Carrega documentos de diferentes fontes.
    Atualmente carrega apenas PDF, mas preparado para expansão futura.
    """
    all_docs = []
    
    # 1. Carregar arquivo PDF (rulebook)
    pdf_path = "../RAG_Docs/rulebook.pdf"
    if os.path.exists(pdf_path):
        pdf_loader = PyPDFLoader(pdf_path)
        pdf_docs = pdf_loader.load()
        
        # Adicionar metadados aos documentos PDF
        for doc in pdf_docs:
            doc.metadata.update({
                "source": "rulebook.pdf",
                "tipo": "rulebook",
                "file_type": "pdf"
            })
        
        all_docs.extend(pdf_docs)
        print(f"Carregados {len(pdf_docs)} páginas do PDF")
    else:
        print(f"Arquivo PDF não encontrado em: {pdf_path}")
    
    # TODO: Futuras expansões para outros tipos de arquivo
    # 
    # 2. Carregar arquivos de texto (quando necessário)
    # text_files = glob.glob("../docs/*.txt")
    # for text_file in text_files:
    #     text_loader = TextLoader(text_file, encoding="utf-8")
    #     text_docs = text_loader.load()
    #     for doc in text_docs:
    #         doc.metadata.update({
    #             "source": os.path.basename(text_file),
    #             "tipo": "text_document",
    #             "file_type": "txt"
    #         })
    #     all_docs.extend(text_docs)
    #
    # 3. Carregar páginas web (quando necessário)
    # urls = ["https://example.com"]
    # web_loader = WebBaseLoader(urls)
    # web_docs = web_loader.load()
    # for doc in web_docs:
    #     doc.metadata.update({
    #         "source": "web",
    #         "tipo": "web_content",
    #         "file_type": "html"
    #     })
    # all_docs.extend(web_docs)
    
    return all_docs


def get_embeddings():
    """
    Configura e retorna o modelo de embeddings
    """
    try:
        # Tentar Ollama primeiro
        embeddings = OllamaEmbeddings(model="nomic-embed-text")
        test_embedding = embeddings.embed_query("test")
        print("Usando Ollama embeddings")
        return embeddings
    except Exception as e:
        print(f"Ollama não disponível: {e}")
        try:
            # Fallback para HuggingFace
            from langchain_community.embeddings import HuggingFaceEmbeddings
            embeddings = HuggingFaceEmbeddings(
                model_name="all-MiniLM-L6-v2",
                model_kwargs={'device': 'cpu'}
            )
            print("Usando HuggingFace embeddings")
            return embeddings
        except Exception as e2:
            print(f"Erro com HuggingFace embeddings: {e2}")
            return None


def load_existing_vectorstore():
    """
    Carrega um vector store existente se disponível
    """
    chroma_db_path = "../Classifier_XML/vector_db"
    
    if os.path.exists(chroma_db_path):
        try:
            embeddings = get_embeddings()
            if embeddings:
                vectorstore = Chroma(
                    persist_directory=chroma_db_path,
                    embedding_function=embeddings,
                    collection_name="robot_agent_docs"
                )
                print(f"Vector store carregado de: {chroma_db_path}")
                return vectorstore
        except Exception as e:
            print(f"Erro ao carregar vector store existente: {e}")
    
    return None


def create_vector_store(documents, batch_size=10):
    """
    Cria o vector store com ChromaDB a partir dos documentos carregados.
    Processa em batches para melhor performance.
    """
    if not documents:
        print("Nenhum documento encontrado para processar.")
        return None
    
    # Dividir documentos em chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", "!", "?", ";", ":", " ", ""]
    )
    chunks = splitter.split_documents(documents)
    print(f"Documentos divididos em {len(chunks)} chunks")
    
    # Caminho para o ChromaDB
    chroma_db_path = "../Classifier_XML/vector_db"
    
    embeddings = get_embeddings()
    if not embeddings:
        print("Não foi possível configurar embeddings.")
        return None
    
    try:
        # Processar em batches menores
        vectorstore = None
        
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i+batch_size]
            print(f"Processando batch {i//batch_size + 1}/{(len(chunks) + batch_size - 1)//batch_size}")
            
            if vectorstore is None:
                # Criar novo vector store com o primeiro batch
                vectorstore = Chroma.from_documents(
                    batch,
                    embeddings,
                    persist_directory=chroma_db_path,
                    collection_name="robot_agent_docs"
                )
            else:
                # Adicionar ao vector store existente
                vectorstore.add_documents(batch)
        
        print(f"Vector store criado/atualizado em: {chroma_db_path}")
        return vectorstore
        
    except Exception as e:
        print(f"Erro ao criar vector store: {e}")
        return None


# Configuração inicial - tenta carregar existente primeiro
print("Inicializando RAG Pipeline...")
vectorstore = load_existing_vectorstore()

if not vectorstore:
    print("Vector store não encontrado. Criando novo...")
    all_docs = load_documents()
    if all_docs:
        vectorstore = create_vector_store(all_docs, batch_size=5)  # Batches menores
    else:
        print("Nenhum documento carregado.")
        vectorstore = None
else:
    print("Vector store existente carregado com sucesso!")

def normalize_query(query):
    """
    Normaliza a consulta do usuário para melhorar a busca vetorial
    Focada em termos de robótica e competições
    """
    query_lower = query.lower()
    
    # Normalizações específicas para robótica
    robotics_normalizations = {
        'robô': 'robot',
        'robo': 'robot',
        'robôs': 'robots',
        'robos': 'robots',
        'navegação': 'navigation',
        'navegacao': 'navigation',
        'competição': 'competition',
        'competicao': 'competition',
        'tarefa': 'task',
        'tarefas': 'tasks',
        'manipulação': 'manipulation',
        'manipulacao': 'manipulation',
        'percepção': 'perception',
        'percepcao': 'perception',
        'localização': 'localization',
        'localizacao': 'localization',
        'mapeamento': 'mapping',
        'planejamento': 'planning',
        'comando': 'command',
        'comandos': 'commands',
        'regra': 'rule',
        'regras': 'rules'
    }
    
    # Aplicar normalizações
    for term, replacement in robotics_normalizations.items():
        query_lower = query_lower.replace(term, replacement)
    
    return [query_lower, query]  # Retorna versão normalizada e original

def get_context(query, k=4):
    """
    Busca contexto relevante no vector store
    """
    if not vectorstore:
        return "Vector store não inicializado."
    
    # Obter variações da consulta normalizada
    query_variations = normalize_query(query)
    
    # Combinar todos os resultados únicos
    all_results = []
    seen_content = set()
    
    # Fazer busca com cada variação da consulta
    for variation in query_variations:
        results = vectorstore.similarity_search(variation, k=k)
        for doc in results:
            if doc.page_content not in seen_content:
                all_results.append(doc)
                seen_content.add(doc.page_content)
    
    # Se não encontrou resultados com variações, tentar busca original
    if not all_results:
        results = vectorstore.similarity_search(query, k=k)
        all_results = results
    
    # Priorizar documentos por tipo se necessário
    rulebook_results = []
    other_results = []
    
    for doc in all_results:
        doc_tipo = doc.metadata.get('tipo', '')
        if 'rulebook' in doc_tipo:
            rulebook_results.append(doc)
        else:
            other_results.append(doc)
    
    # Priorizar rulebook para consultas sobre regras/competição
    if any(termo in query.lower() for termo in ['rule', 'regra', 'competition', 'competição', 'task', 'tarefa', 'score', 'pontuação']):
        final_results = (rulebook_results + other_results)[:k]
    else:
        final_results = all_results[:k]
    
    # Retornar contexto concatenado
    context = "\n\n".join([doc.page_content for doc in final_results])
    return context if context.strip() else "Nenhum contexto relevante encontrado."

def debug_search(query, k=3):
    """
    Função de debug para verificar resultados de busca
    """
    if not vectorstore:
        print("Vector store não disponível.")
        return
    
    print(f"Debug: Buscando por '{query}'")
    results = vectorstore.similarity_search(query, k=k)
    print(f"Encontrados {len(results)} resultados:")
    
    for i, doc in enumerate(results, 1):
        preview = doc.page_content[:150].replace('\n', ' ')
        source = doc.metadata.get('source', 'unknown')
        doc_type = doc.metadata.get('tipo', 'unknown')
        print(f"  {i}: [{source} - {doc_type}] {preview}...")


def get_vectorstore():
    """
    Retorna o vectorstore para uso externo
    """
    return vectorstore


def add_documents_to_vectorstore(new_documents):
    """
    Adiciona novos documentos ao vector store existente
    Útil para expansões futuras
    """
    global vectorstore
    
    if not new_documents:
        print("Nenhum documento fornecido para adicionar.")
        return False
    
    try:
        # Dividir novos documentos em chunks
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150,
            separators=["\n\n", "\n", ".", "!", "?", ";", ":", " ", ""]
        )
        new_chunks = splitter.split_documents(new_documents)
        
        # Adicionar ao vector store existente
        if vectorstore:
            vectorstore.add_documents(new_chunks)
            print(f"Adicionados {len(new_chunks)} chunks ao vector store.")
            return True
        else:
            print("Vector store não inicializado.")
            return False
            
    except Exception as e:
        print(f"Erro ao adicionar documentos: {e}")
        return False


def search_with_filter(query, metadata_filter=None, k=4):
    """
    Busca com filtros de metadata
    Exemplo: search_with_filter("navigation", {"tipo": "rulebook"})
    """
    if not vectorstore:
        return "Vector store não disponível."
    
    try:
        if metadata_filter:
            results = vectorstore.similarity_search(query, k=k, filter=metadata_filter)
        else:
            results = vectorstore.similarity_search(query, k=k)
        
        return "\n\n".join([doc.page_content for doc in results])
        
    except Exception as e:
        print(f"Erro na busca com filtro: {e}")
        return get_context(query, k)  # Fallback para busca normal


if __name__ == "__main__":
    # Teste do sistema
    print("Sistema RAG para Robot Agent carregado!")
    
    if vectorstore:
        print(f"Vector store inicializado com sucesso.")
        print("Testando busca básica:")
        
        test_queries = [
            "robot navigation",
            "competition rules",
            "task execution",
            "manipulation"
        ]
        
        for query in test_queries:
            print(f"\n--- Consulta: {query} ---")
            context = get_context(query, k=2)
            preview = context[:200] if context else "Sem resultado"
            print(f"Resultado: {preview}...")
    else:
        print("Erro: Vector store não foi inicializado.")
        print("Verifique se os documentos foram carregados corretamente.")