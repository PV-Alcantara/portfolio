from pyspark.sql import SparkSession
from pyspark.dbutils import DBUtils
from abc import ABC
import requests
import pandas as pd
import io

# Inicializa Spark e DBUtils
spark = SparkSession.builder.getOrCreate()
dbutils = DBUtils(spark)

# Função para recuperar segredos
def get_secret(scope, key):
    try:
        return dbutils.secrets.get(scope, key)
    except Exception as e:
        raise ValueError(f"Erro ao buscar segredo: {e}. Verifique o escopo '{scope}' e a chave '{key}'.")

# URLs de autenticação e mensagens
URL_TOKEN = "https://login.microsoftonline.com/xxxxxx-xxxx-xxxx-xxxx-xxxxxxxx/oauth2/v2.0/token"
URL_MSG = "https://graph.microsoft.com/v1.0/sites/"

# Classe Sharepoint para extração de dados
class Sharepoint(ABC):
    def __init__(self, path_file, name_site="DadosBI", host="achelaboratorios.sharepoint.com"):
        self.path_file, self.name_site, self.host = path_file, name_site, host
        self.headers = self.get_bearer_token()
        self.data = self.download_file()

    def get_bearer_token(self):
        body = {
            "grant_type": "client_credentials",
            "client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxx",
            "client_secret": get_secret("keyvault", "key-trdg-client-secret"),
            "scope": "https://graph.microsoft.com/.default",
        }
        token = requests.post(URL_TOKEN, data=body).json()['access_token']
        return {"Accept": "application/json", "Authorization": f"Bearer {token}"}

    def get_ids(self, is_file=True):
        id_site = requests.get(f"{URL_MSG}/{self.host}:/sites/{self.name_site}?$select=id", headers=self.headers).json()["id"].split(",")[1]
        id_drives = requests.get(f"{URL_MSG}{id_site}/drive", headers=self.headers).json()["id"]
        return f"{URL_MSG}{id_site}/drives/{id_drives}/root:/{self.path_file}:{'/content' if is_file else '/children'}"

    def download_file(self):
        return requests.get(self.get_ids(is_file="." in self.path_file), headers=self.headers).content

    def read_file(self, encoding="utf-8", **params):
        ext = self.path_file.split(".")[-1]
        read_funcs = {"txt": pd.read_csv, "csv": pd.read_csv, "xls": pd.read_excel, "xlsx": pd.read_excel}
        if ext in read_funcs:
            self.read_data = read_funcs[ext](io.StringIO(self.data.decode(encoding)) if ext in ["txt", "csv"] else self.data, **params)
        else:
            raise ValueError("Tipo de arquivo não suportado!")
        return self

    def to_dataframe(self):
        return self.read_data

