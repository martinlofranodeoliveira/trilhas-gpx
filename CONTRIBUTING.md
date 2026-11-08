# Contribuir

Abra uma issue com comportamento esperado, observado, versão do Python e fixture **fictícia mínima**. Não envie trajetos privados, endereços, coordenadas pessoais ou credenciais.

1. Crie uma branch.
2. Preserve a semântica documentada de distância, cobertura e interrupções.
3. Acrescente testes públicos que falhem antes da correção; não enfraqueça os existentes.
4. Execute `python3 -B scripts/check.py` em Linux com as ferramentas documentadas.
5. Atualize API/METODO quando alterar contrato e explique compatibilidade.

O verificador testa uma instalação real a partir do sdist/wheel em namespace sem rede e credenciais. Não execute comandos recebidos de arquivos GPX; o parser não tem essa capacidade. Mudanças no harness exigem revisão independente das propriedades de isolamento e testes.

Toda contribuição deve permitir distribuição sob MIT e preservar atribuições. Não incluir novos percursos reais ou dependências de mapas externos sem finalidade e licença explícitas.
