@app.route('/receipt_all_vendors', methods=['GET', 'POST'])
def receipt_all_vendors():

    if 'id' not in session:
        return redirect(url_for('login'))

    user_id = int(session.get('id'))

    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == 'POST':

        from_date = request.form.get('from_date')
        to_date = request.form.get('to_date')

        # ---------- rates ----------
        cursor.execute(
            "SELECT * FROM milk_rates WHERE user_id=%s ORDER BY date_from DESC",
            (user_id,)
        )
        rate_data = cursor.fetchall()

        def get_rate(animal, entry_date):
            if isinstance(entry_date, str):
                entry_date = datetime.strptime(entry_date,"%Y-%m-%d").date()

            for r in rate_data:
                rate_date = r['date_from']
                if isinstance(rate_date,str):
                    rate_date = datetime.strptime(rate_date,"%Y-%m-%d").date()

                if r['animal'] == animal and entry_date >= rate_date:
                    return float(r['rate'])

            return 0

        # ---------- vendors ----------
        cursor.execute("""
            SELECT vendor_id,name,milk_type,address
            FROM vendors
            WHERE user_id=%s
            ORDER BY vendor_id ASC
        """,(user_id,))
        vendors = cursor.fetchall()

        # ---------- milk (single query) ----------
        cursor.execute("""
            SELECT vendor_id,DATE(date) AS full_date,
                   DATE_FORMAT(date,'%%d') AS day,
                   slot,milk_type,quantity
            FROM milk_collection
            WHERE user_id=%s
            AND date BETWEEN %s AND %s
            ORDER BY date ASC
        """,(user_id,from_date,to_date))

        milk_rows = cursor.fetchall()

        milk_map = {}

        for r in milk_rows:
            vid = r['vendor_id']
            milk_map.setdefault(vid,[]).append(r)

        # ---------- food sack (single query) ----------
        cursor.execute("""
            SELECT fs.vendor_id,fs.sack_qty,r.name,r.rate,
                   (fs.sack_qty*r.rate) total
            FROM food_sack fs
            JOIN food_sack_rates r ON fs.sack_rate_id=r.id
            WHERE fs.user_id=%s
            AND fs.date BETWEEN %s AND %s
        """,(user_id,from_date,to_date))

        food_rows = cursor.fetchall()

        food_map = {}

        for f in food_rows:
            food_map.setdefault(f['vendor_id'],[]).append(f)

        # ---------- advance (single query) ----------
        cursor.execute("""
            SELECT vendor_id,SUM(amount) total
            FROM advance
            WHERE user_id=%s
            AND date BETWEEN %s AND %s
            GROUP BY vendor_id
        """,(user_id,from_date,to_date))

        adv_rows = cursor.fetchall()

        adv_map = {a['vendor_id']:a['total'] for a in adv_rows}

        all_receipts = []

        for vendor in vendors:

            vid = vendor['vendor_id']

            milk_data = milk_map.get(vid,[])

            grouped = {}

            totals = {
                'cow_morning':0,
                'cow_evening':0,
                'buffalo_morning':0,
                'buffalo_evening':0
            }

            cow_cost = 0
            buffalo_cost = 0

            for row in milk_data:

                dt = row['full_date']
                slot = row['slot']
                mtype = row['milk_type']
                qty = float(row['quantity'])

                rate = get_rate(mtype,dt)

                if dt not in grouped:
                    grouped[dt] = {
                        'day':row['day'],
                        'cow_morning':0,
                        'cow_evening':0,
                        'buffalo_morning':0,
                        'buffalo_evening':0
                    }

                grouped[dt][f"{mtype}_{slot}"] += qty
                totals[f"{mtype}_{slot}"] += qty

                if mtype == "cow":
                    cow_cost += qty*rate
                else:
                    buffalo_cost += qty*rate

            entries = list(grouped.values())

            food_data = food_map.get(vid,[])

            food_total = sum(f['total'] for f in food_data) if food_data else 0

            food_sack_details = [
                {
                    "name":f['name'],
                    "rate":f['rate'],
                    "qty":f['sack_qty'],
                    "total":f['total']
                }
                for f in food_data
            ]

            advance = adv_map.get(vid,0) or 0

            final_payable = round((cow_cost+buffalo_cost)-(advance+food_total),2)

            cow_rate = get_rate('cow',datetime.strptime(from_date,"%Y-%m-%d").date())
            buffalo_rate = get_rate('buffalo',datetime.strptime(from_date,"%Y-%m-%d").date())

            all_receipts.append({

                'vendor_id':vid,
                'name':vendor['name'],
                'address':vendor['address'],
                'milk_type':vendor['milk_type'],

                'data':entries,

                'total_cow':totals['cow_morning']+totals['cow_evening'],
                'total_buffalo':totals['buffalo_morning']+totals['buffalo_evening'],

                'cow_cost':round(cow_cost,2),
                'buffalo_cost':round(buffalo_cost,2),

                'food_sack_details':food_sack_details,
                'food_cost':food_total,

                'advance':advance,
                'final_payable':final_payable,

                'total_cow_morning':totals['cow_morning'],
                'total_cow_evening':totals['cow_evening'],

                'total_buffalo_morning':totals['buffalo_morning'],
                'total_buffalo_evening':totals['buffalo_evening'],

                'cow_rate':cow_rate,
                'buffalo_rate':buffalo_rate
            })

        cursor.close()

        return render_template(
            'receipt_all_vendors.html',
            receipts=all_receipts
        )

    cursor.close()

    return render_template(
        'receipt_all_vendors.html',
        receipts=None
    )