import pandas as pd
import datetime as dt
from pyspark.sql import SparkSession
from pyspark.sql.functions import col
from import_sharepoint import Sharepoint

campanha = Sharepoint('General/Arquivo_Databricks/Campanhas_Ativas.xlsx').read_file(engine = 'openpyxl').to_dataframe()

logix = pd.DataFrame(data=campanha)

# Copia do DataFrame para versão full
logix_full = logix.copy()

# DataFrame resumido
logix = logix.loc[:, ['ObjetivoCampanha', 'Data_Inicio_Vigencia', 'Data_Fim_Compra']].copy()

############# INÍCIO DO TRATAMENTO DAS DATAS ######################

# Função para ajustar as datas
def adjust_dates(start_date, end_date):
    today = dt.date.today()
    start_date = pd.to_datetime(start_date, format='%d/%m/%Y')
    end_date = pd.to_datetime(end_date, format='%d/%m/%Y')

    if end_date.year > today.year:
        end_date = end_date.replace(year=today.year, month=12, day=31)
    else:
        end_date = pd.to_datetime(end_date)

    return start_date, end_date

# Aplica a função de ajuste de datas
logix[['Data_Inicio_Vigencia', 'Data_Fim_Compra']] = logix.apply(
    lambda row: pd.Series(adjust_dates(row[1], row[2])), axis=1
)

logix = logix.drop_duplicates("ObjetivoCampanha")

############# REPETIÇÃO DAS DATAS ######################

# Função para expandir as datas
def expand_dates(df):
    rows = []
    for _, row in df.iterrows():
        start_date = row['Data_Inicio_Vigencia'] 
        end_date = row['Data_Fim_Compra']
        while start_date <= end_date:
            new_row = row.copy()
            new_row['Data_Inicio_Vigencia'] = start_date
            rows.append(new_row)
            start_date += pd.DateOffset(days=1)
    return pd.DataFrame(rows)

logix_expanded = expand_dates(logix)

# Limpeza do código EAN e Desconto
logix_full['EAN'] = logix_full['EAN'].str.replace("'", "", regex=False)
logix_full['Desconto'] = logix_full['Desconto'].str.replace(",", ".", regex=False).astype(float)

#### PREENCHIMENTO DA TABELA FINAL/CRIAÇÃO TABELA FÍSICA LOGIX #######

spark = SparkSession.builder.appName("pandas to spark").getOrCreate()

logix_expanded_spark = spark.createDataFrame(logix_expanded)
logix_full_spark = spark.createDataFrame(logix_full)

logix_expanded_spark.createOrReplaceTempView("logix_expanded")
logix_full_spark.createOrReplaceTempView("logix_full")

logix_final = spark.sql("""
    SELECT 
        logix_full.Status_Campanha,
        logix_full.CodCampanha,
        logix_full.Campanha, 
        logix_full.ObjetivoCampanha,
        logix_full.Possui_Cupom as Cupom,
        logix_full.Controle_Limite, 
        logix_full.EAN, 
        logix_expanded.Data_Inicio_Vigencia, 
        logix_full.Desconto  
    FROM 
        logix_full 
    LEFT JOIN 
        logix_expanded ON logix_expanded.ObjetivoCampanha = logix_full.ObjetivoCampanha
""")

# Ajuste final da coluna desconto para float
logix_final = logix_final.withColumn("Desconto", col("Desconto").cast("float"))

# Remoção de duplicatas
logix_final = logix_final.dropDuplicates(['Data_Inicio_Vigencia', 'EAN', 'ObjetivoCampanha'])

#### CRIAÇÃO DA TABELA FATO CAMPANHA #######

logix_final.createOrReplaceTempView("logix_final")

logix_final = spark.sql("""
    SELECT
        fvend.DATA_COMPRA,
        fvend.ID_PORTADOR,
        fvend.EAN,
        fvend.ID_LOJA,
        fvend.ID_MEDICO,
        fcampanha.CodCampanha,
        fcampanha.Campanha,
        fcampanha.ObjetivoCampanha,
        fcampanha.Cupom,
        fcampanha.Controle_Limite,
        fcampanha.Desconto,
        fcampanha.Status_Campanha,
        SUM(fvend.QUANTIDADE) AS UND,
        SUM(fvend.Faturamento) AS FAT,
        SUM(fvend.PRIMEIRA_COMPRA) AS PRIMEIRA_COMPRA
    FROM
        dmn_transformacao_digital_dev.db_analytics.cpv_fvendas AS fvend
    INNER JOIN
        logix_final AS fcampanha
        ON fcampanha.Data_Inicio_Vigencia = fvend.DATA_COMPRA
        AND fcampanha.EAN = fvend.EAN
        AND int(fcampanha.CodCampanha) = int(fvend.ID_CAMPANHA)
    WHERE
        YEAR(fvend.DATA_COMPRA) >= YEAR(GETDATE()) - 3
    GROUP BY
        fvend.DATA_COMPRA,
        fvend.ID_PORTADOR,
        fvend.EAN,
        fvend.ID_LOJA,
        fvend.ID_MEDICO,
        fcampanha.CodCampanha,
        fcampanha.Campanha,
        fcampanha.ObjetivoCampanha,
        fcampanha.Cupom,
        fcampanha.Controle_Limite,
        fcampanha.Desconto,
        fcampanha.Status_Campanha
""")

# Salvar a tabela final
logix_final.write.mode("overwrite").saveAsTable("dmn_transformacao_digital_dev.db_analytics.CPV_fCampanhas")

