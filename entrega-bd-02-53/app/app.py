import os
from flask import Flask, request, jsonify
from psycopg_pool import ConnectionPool

app = Flask(__name__)

db_url = "postgres://app:app@postgres/app"
pool = ConnectionPool(db_url)

@app.route("/zona/<int:zona>/", methods=("GET",))
def zona_index(zona):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            if not cur.execute("SELECT 1 FROM zona WHERE id_zona = %(zona)s;", {"zona": zona}).fetchone():
                return jsonify({"message": "Zona não encontrada.", "status": "error"}), 404

            recintos_brutos = cur.execute(
                """
                SELECT r.id_recinto, e.nome_cientifico, e.nome_comum, COUNT(a.id_animal) AS num_animais
                FROM recinto r
                LEFT JOIN animal a ON r.id_recinto = a.id_recinto
                LEFT JOIN especie e ON a.nome_cientifico = e.nome_cientifico
                WHERE r.id_zona = %(zona)s
                GROUP BY r.id_recinto, e.nome_cientifico, e.nome_comum
                ORDER BY r.id_recinto;
                """,
                {"zona": zona},
            ).fetchall()

    recintos_formatados = {}
    for linha in recintos_brutos:
        id_recinto, nome_cientifico, nome_comum, num_animais = linha

        if id_recinto not in recintos_formatados:
            recintos_formatados[id_recinto] = {
                "numero_recinto": id_recinto,
                "especies": []
            }

        if nome_cientifico:
            recintos_formatados[id_recinto]["especies"].append({
                "nome_cientifico": nome_cientifico,
                "nome_comum": nome_comum,
                "num_animais": num_animais
            })

    return jsonify(list(recintos_formatados.values())), 200

@app.route("/recinto/<int:recinto>/voto/<int:bilhete>/", methods=("POST",))
def recinto_voto_save(recinto, bilhete):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT votou FROM bilhete WHERE bid = %(bid)s", {"bid": bilhete})
            res = cur.fetchone()
            if not res:
                return jsonify({"error": "Bilhete inválido."}), 404
            if res[0]:
                return jsonify({"error": "Bilhete já votou."}), 400

            cur.execute("""
                SELECT 1 FROM acesso a JOIN recinto r ON a.id_zona = r.id_zona 
                WHERE a.bid = %(bid)s AND r.id_recinto = %(rec)s
            """, {"bid": bilhete, "rec": recinto})
            
            if not cur.fetchone():
                return jsonify({"error": "Sem acesso à zona deste recinto."}), 403

            with conn.transaction():
                cur.execute("UPDATE bilhete SET votou = TRUE WHERE bid = %(bid)s", {"bid": bilhete})
                cur.execute("UPDATE recinto SET votos = COALESCE(votos, 0) + 1 WHERE id_recinto = %(rec)s", {"rec": recinto})

    return jsonify({"message": "Voto computado."}), 200

@app.route("/venda/", methods=("POST",))
def venda_save():
    dados = request.get_json()

    if not dados or not dados.get("bilhetes"):
        return jsonify({"error": "É necessário incluir pelo menos um bilhete."}), 400

    bilhetes_req = dados["bilhetes"]
    nif = dados.get("nif", None)

    with pool.connection() as conn:
        with conn.cursor() as cur:
            with conn.transaction():
                cur.execute(
                    "INSERT INTO venda (data_hora, nif_cliente) VALUES (NOW(), %(nif)s) RETURNING no_venda",
                    {"nif": nif}
                )
                no_venda = cur.fetchone()[0]

                resumo_bilhetes = []
                preco_total = 0.0

                for b in bilhetes_req:
                    desconto = b.get("desconto", 0)
                    zonas = b.get("zonas", [])

                    if not zonas:
                        return jsonify({"error": "Cada bilhete precisa de pelo menos uma zona."}), 400

                    cur.execute(
                        "INSERT INTO bilhete (no_venda, desconto) VALUES (%(nv)s, %(desc)s) RETURNING bid",
                        {"nv": no_venda, "desc": desconto}
                    )
                    bid = cur.fetchone()[0]

                    for zona_id in zonas:
                        cur.execute(
                            "INSERT INTO acesso (bid, id_zona) VALUES (%(bid)s, %(zid)s)",
                            {"bid": bid, "zid": zona_id}
                        )

                    cur.execute(
                        "SELECT SUM(preco) FROM zona WHERE id_zona = ANY(%(zonas)s)",
                        {"zonas": zonas}
                    )
                    preco_base = float(cur.fetchone()[0] or 0)
                    preco_bilhete = round(preco_base * (1 - desconto / 100), 2)
                    preco_total += preco_bilhete

                    resumo_bilhetes.append({"bid": bid, "preco": preco_bilhete})

    return jsonify({"no_venda": no_venda, "preco_total": round(preco_total, 2), "bilhetes": resumo_bilhetes}), 201

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)