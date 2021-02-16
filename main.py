import datetime
import math

import pandas as pd
# https://pypi.org/project/phonenumbers/
import phonenumbers
from phonenumbers import carrier
from pytimeparse.timeparse import timeparse


def parseNumber(nr: str):
    nr = str(nr)
    print("Parsing nr [{}]".format(nr))
    if len(nr) == 9: nr = str("+36{}".format(nr))
    if len(nr) == 11: nr = str("+{}".format(nr))
    # Hordozott szám :(
    if nr == "+36301837880": nr = "+36201837880"
    if nr == 'nan': nr= "+36201837880" # hidden number
    return phonenumbers.parse(nr, "HU")


class Szerzodes:
    yearMonth = -1
    maradek_ingyen_percek = 0
    maradek_ingyen_percek_sajat = 0
    last_cr_date = datetime.datetime.strptime("1970 01 01", "%Y %m %d")

    def __init__(self, desc: str, carrier: str, base='perc', ingyen_percek=0.0,
                 ingyen_percek_sajat=0.0,
                 alap_dij=0, perc_dij=0, netGB=0, yearMonth=-1):
        self.desc = desc
        self.carrier = carrier
        self.base = base
        self.ingyen_percek = ingyen_percek
        self.alap_dij = int(alap_dij)
        self.ingyen_percek_sajat = ingyen_percek_sajat
        self.perc_dij = int(perc_dij)
        self.netGB = netGB
        self.yearMonth = yearMonth
        self.fizetendo={}

    def __str__(self):
        r = f"Név:                           {self.desc}\n"
        r += f"Szolg:                         {self.carrier}\n"
        r += f"Alapdíj:                       {self.alap_dij}\n"
        r += f"Számlázás alapja:              {self.base}\n"
        r += f"Ingyen percek:                 {self.ingyen_percek}\n"
        r += f"Ingyen percek hálózaton belül: {self.ingyen_percek_sajat}\n"
        r += f"Percdíj:                       {self.perc_dij} Ft\n"
        r += f"Mobilnet:                      {self.netGB}GB\n"
        r += f""
        return r


class CallRecord:
    def __init__(self, dict):
        self.fromName = dict["Name"]
        self.type = dict["Type"]

        # "Sr.No", "Name", "From Number", "To Number", "Date", "Time", "Duration", "Type"
        # "1", "Dóri", "301835550", "+36205559280", "2020-12-31", "05:54 PM", "00s", "Missed"
        print (dict)
        # self.fromNumber = parseNumber(dict["From Number"])
        self.toNumber = parseNumber(dict["To Number"])
        self.toCarrier = carrier.name_for_number(self.toNumber, "hu")

        f = "{} {}".format(dict["Date"], dict["Time"])
        self.start = datetime.datetime.strptime(f, "%Y-%m-%d %I:%M %p")
        self.yearMonth = int(self.start.strftime("%Y%m"))
        # self.duration = dict["Duration"]
        # 09s
        # 14m 52s
        # 01h 14m 52s
        # d = "0+" + str(dict["Duration"])
        # d = int(eval(d.replace(" ", "+").replace("s", "").replace("m", "*60").replace("h", "*3600").replace("+0", "+").replace("^0", "")))
        self.end = self.start + datetime.timedelta(0, timeparse(str(dict["Duration"])))
        self.duration = self.end - self.start
        self.hossz_perc = math.ceil(self.duration.seconds / 60)
        self.szamolt_dij = None

    def __repr__(self):
        r = "{} (duration: {}: {} mins)".format(self.start,
                                                str(self.duration),
                                                self.hossz_perc
                                                )
        r += " - type: {}".format(self.type)
        return r

    def get_szamolt_dij(self, szerzodes: Szerzodes):
        if szerzodes.last_cr_date > cr.start:
            raise Exception(
                "Error: nem időrendi sorrendben érkeznek be a rekordok, így nem lehet feldolgozni őket.\n{}".format(
                    self))
        szerzodes.last_cr_date = cr.start
        self.szamolt_dij = 0

        if szerzodes.yearMonth != self.yearMonth:
            print("*** Új hónap kezdődik! *** {} -> {}".format(szerzodes.yearMonth, self.yearMonth))
            if szerzodes.yearMonth >0: print("Előző havi díj: {}".format(szerzodes.fizetendo[str(szerzodes.yearMonth)]))
            szerzodes.yearMonth = self.yearMonth
            szerzodes.fizetendo[str(szerzodes.yearMonth)] = szerzodes.alap_dij
            szerzodes.maradek_ingyen_percek = szerzodes.ingyen_percek
            szerzodes.maradek_ingyen_percek_sajat = szerzodes.ingyen_percek_sajat

        if self.type != 'Outgoing': return 0
        if self.hossz_perc == 0: return 0
        halozaton_belul = szerzodes.carrier == self.toCarrier
        perc_dij = szerzodes.perc_dij
        fizetendo_perc = self.hossz_perc

        if halozaton_belul:
            if szerzodes.maradek_ingyen_percek_sajat > 0:
                if fizetendo_perc <= szerzodes.maradek_ingyen_percek_sajat:
                    # elég a keret
                    szerzodes.maradek_ingyen_percek_sajat = szerzodes.maradek_ingyen_percek_sajat - fizetendo_perc
                    fizetendo_perc = 0
                    print("{} ingyen perc elhasználva, marad még {} ingyen perc saját hálózaton belül.".format(
                        self.hossz_perc, szerzodes.maradek_ingyen_percek_sajat))
                else:
                    # nem elég a keret
                    fizetendo_perc = fizetendo_perc - szerzodes.maradek_ingyen_percek_sajat
                    szerzodes.maradek_ingyen_percek_sajat = 0
                    print(
                        "{} ingyen perc elhasználva, viszont ezzel elfogyott a saját hálózaton belüli ingyen perc, sőt, még {} elszámolandó.".format(
                            1, 2))

        if fizetendo_perc > 0:
            if szerzodes.maradek_ingyen_percek > 0:
                if fizetendo_perc <= szerzodes.maradek_ingyen_percek:
                    szerzodes.maradek_ingyen_percek = szerzodes.maradek_ingyen_percek - fizetendo_perc
                    fizetendo_perc = 0
                    print("Marad még {} ingyen perc".format(szerzodes.maradek_ingyen_percek))
                else:
                    fizetendo_perc = fizetendo_perc - szerzodes.maradek_ingyen_percek
                    szerzodes.maradek_ingyen_percek = 0
                    print("Ezzel elfogyott az ingyen perc, {} percet fizetni kell.".format(fizetendo_perc))

        self.szamolt_dij = fizetendo_perc * perc_dij
        szerzodes.fizetendo[str(szerzodes.yearMonth)] += self.szamolt_dij
        return self.szamolt_dij


class number:
    def __init__(self, numberStr: str):
        self.country = 36
        self.korzet = 43


def getElofizetesek():
    elofizetesek = []

    elofizetesek.append(
        Szerzodes(desc="DigiMobil+", carrier="Digi", ingyen_percek=200,
                  alap_dij=1000, netGB=15, perc_dij=4))

    # Telenor S: (Telenor)
    #  - 5400Ft
    #  - 100 perc, 3GB
    #  - korlátlan Telenor
    elofizetesek.append(
        Szerzodes(desc="Telenor S", carrier="Telenor", ingyen_percek=100, ingyen_percek_sajat=math.inf,
                  alap_dij=5400, netGB=3))

    # HiperNet Talk M: (Telenor)
    #  - 8000Ft
    #  - korlátlan beszéd, 5GB
    elofizetesek.append(
        Szerzodes(desc="HNet Talk M(Telenor)", carrier="Telenor", ingyen_percek=math.inf, ingyen_percek_sajat=math.inf,
                  alap_dij=8000, netGB=5))

    # Go Talk+(Vodafone)
    #  - 8000Ft
    #  - korlátlan beszéd
    #  - 2GB
    elofizetesek.append(
        Szerzodes(desc="Go Talk+", carrier="Vodafone", ingyen_percek=math.inf,
                  alap_dij=8000, netGB=2))

    elofizetesek.append(
        Szerzodes(desc="Telenor XS+", carrier="Telenor", ingyen_percek=100,
                  alap_dij=4000, netGB=3, perc_dij=40))




    # Go easy (Vodafone):
    #  - 4500 Ft
    #  - 20Ft/perc, 15GB (10GB hűség nélkül)
    elofizetesek.append(
        Szerzodes(desc="Go easy", carrier="Vodafone", alap_dij=4500,
                  netGB=15, perc_dij=20))
    elofizetesek.append(
        Szerzodes(desc="Go easy - hűség n.", carrier="Vodafone",
                  alap_dij=4500, netGB=10, perc_dij=20))

    # Go next (Vodafone)
    #  - 6000Ft
    #  - 200perc, 3GB
    #  - 40 Ft/perc
    elofizetesek.append(
        Szerzodes(desc="Go next", carrier="Vodafone", ingyen_percek=200,
                  alap_dij=6000, netGB=3, perc_dij=40))

    #
    # Go mini (Vodafone)
    #  - 3000Ft
    #  - 100perc, 2GB
    #  - 40 Ft/perc
    elofizetesek.append(
        Szerzodes(desc="Go mini", carrier="Vodafone", ingyen_percek=100,
                  alap_dij=3000, netGB=2, perc_dij=40))

    # [print(szerzodes) for szerzodes in elofizetesek]

    # DEMO
    # elofizetesek = []
    # elofizetesek.append(
    #     Szerzodes(desc="Go mini", carrier="Vodafone", ingyen_percek=100,
    #                alap_dij=3000, netGB=2, perc_dij=40))

    return elofizetesek


def import_csv(fle: str):
    # return [tuple(x) for x in df.values]
    # return [[row[col] for col in df.columns] for row in df.to_dict('records')]
    return pd.read_csv(fle, delimiter=',').to_dict('records')


def get_callRecords(fle: str):
    return [CallRecord(line) for line in reversed(import_csv(fle))]


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    elofizetesek = getElofizetesek()
    input="Report_2020_Sanyi"
    call_records = get_callRecords(f'./input/{input}.csv')

    for e in elofizetesek:
        print("\n********************************\nSzerződés: {}({})".format(e.desc, e.carrier))
        print(e)
        for cr in call_records:
            print("\n {}: {} call, len: {} min {}->{}".format(cr.start.strftime('%m.%d %H:%M'), cr.type, cr.hossz_perc,
                                                              e.carrier, cr.toCarrier))
            cr.get_szamolt_dij(e)
            print("  Díj: {} Ft".format(cr.szamolt_dij))

    import pandas as pd
    import numpy as np

    # yms=elofizetesek[0].fizetendo.keys()


    data={}
    for e in elofizetesek:
        data[e.desc]=list(e.fizetendo.values())
    df=pd.DataFrame(data,index=list(elofizetesek[0].fizetendo.keys()))

    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    print(df)

    # df.to_csv('output.csv', index = True,sep='\t')

    ew = pd.ExcelWriter(f'{input}.xlsx')
    df.to_excel(ew, index=True)
    ew.save()
