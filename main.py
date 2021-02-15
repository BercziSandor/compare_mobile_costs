import pandas as pd
from pprint import pprint
# https://pypi.org/project/phonenumbers/
import phonenumbers
from phonenumbers import carrier
import datetime
from pytimeparse.timeparse import timeparse
import math


def parseNumber(nr: str):
    nr = str(nr)
    if len(nr) == 9: nr = str("+36{}".format(nr))
    if len(nr) == 11: nr = str("+{}".format(nr))
    # Hordozott szám :(
    if nr == "+36301837880": nr = "+36201837880"
    return phonenumbers.parse(nr, "HU")


class callRecord:
    def __init__(self, dict):
        self.fromName = dict["Name"]
        self.type = dict["Type"]

        # "Sr.No", "Name", "From Number", "To Number", "Date", "Time", "Duration", "Type"
        # "1", "Dóri", "301835550", "+36205559280", "2020-12-31", "05:54 PM", "00s", "Missed"

        self.fromNumber = parseNumber(dict["From Number"])
        self.toNumber = parseNumber(dict["To Number"])
        self.toCarrier = carrier.name_for_number(self.toNumber, "hu")
        # self.sameCarrier = carrier.name_for_number(self.fromNumber, "hu") == carrier.name_for_number(self.toNumber, "hu")

        f = "{} {}".format(dict["Date"], dict["Time"])
        self.start = datetime.datetime.strptime(f, "%Y-%m-%d %H:%M %p")
        self.yearMonth = self.start.strftime("%Y%m")
        # self.duration = dict["Duration"]
        # 09s
        # 14m 52s
        # 01h 14m 52s
        # d = "0+" + str(dict["Duration"])
        # d = int(eval(d.replace(" ", "+").replace("s", "").replace("m", "*60").replace("h", "*3600").replace("+0", "+").replace("^0", "")))
        self.end = self.start + datetime.timedelta(0, timeparse(str(dict["Duration"])))
        self.duration = self.end - self.start
        self.hossz_perc = math.ceil(self.duration.seconds / 60)

    def __repr__(self):
        r = "{} (duration: {}: {} mins)".format(self.start,
                                                str(self.duration),
                                                self.hossz_perc
                                                )
        r += " - type: {}".format(self.type)
        r += " - same carrier: {}".format(self.sameCarrier)

        return r


class elofizetes:
    yearMonth = '-1'
    maradek_ingyen_percek = 0
    maradek_ingyen_percek_sajat = 0

    def __init__(self, desc: str, carrier: str, base='perc', ingyen_percek=0.0,
                 ingyen_percek_sajat=0.0,
                 alap_dij=0, perc_dij=0, netGB=0):
        self.desc = desc
        self.carrier = carrier
        self.base = base
        self.ingyen_percek = ingyen_percek
        self.alap_dij = int(alap_dij)
        self.ingyen_percek_sajat = ingyen_percek_sajat
        self.perc_dij = int(perc_dij)
        self.netGB = netGB

    # if sajat_halozat:
    #     if sajat_halozatban_ingyenes:

    def price(self, cr: callRecord):
        if self.yearMonth != callRecord.yearMonth:
            self.yearMonth = callRecord.yearMonth
            self.maradek_ingyen_percek = self.ingyen_percek
            self.maradek_ingyen_percek_sajat = self.ingyen_percek_sajat
        sajat_hivas = self.carrier == cr.toCarrier
        perc_dij=self.perc_dij
        if sajat_hivas:
            if self.maradek_ingyen_percek_sajat > 0:
                if cr.hossz_perc <= self.maradek_ingyen_percek_sajat:
                    self.maradek_ingyen_percek_sajat -= cr.hossz_perc
                    fizetendo_perc = 0
                else:
                    fizetendo_perc = cr.hossz_perc - self.maradek_ingyen_percek_sajat
                    self.maradek_ingyen_percek_sajat = 0

        dij = fizetendo_perc * perc_dij

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


class number:
    def __init__(self, numberStr: str):
        self.country = 36
        self.korzet = 43


def getElofizetesek():
    elofizetesek = []

    # Telenor S: (Telenor)
    #  - 5400Ft
    #  - 100 perc, 3GB
    #  - korlátlan Telenor
    elofizetesek.append(
        elofizetes(desc="Telenor S", carrier="Telenor", ingyen_percek=100, ingyen_percek_sajat=math.inf,
                   alap_dij=5400, netGB=3))

    # HiperNet Talk M: (Telenor)
    #  - 8000Ft
    #  - korlátlan beszéd, 5GB
    elofizetesek.append(
        elofizetes(desc="HiperNet Talk M", carrier="Telenor", ingyen_percek=math.inf, ingyen_percek_sajat=math.inf,
                   alap_dij=8000, netGB=5))

    # Go easy (Vodafone):
    #  - 4500 Ft
    #  - 20Ft/perc, 15GB (10GB hűség nélkül)
    elofizetesek.append(
        elofizetes(desc="Go easy", carrier="Vodafone", alap_dij=4500,
                   netGB=15, perc_dij=20))
    elofizetesek.append(
        elofizetes(desc="Go easy - hűség nélkül", carrier="Vodafone",
                   alap_dij=4500, netGB=10, perc_dij=20))

    # Go next (Vodafone)
    #  - 6000Ft
    #  - 200perc, 3GB
    #  - 40 Ft/perc
    elofizetesek.append(
        elofizetes(desc="Go next", carrier="Vodafone", ingyen_percek=200,
                   alap_dij=6000, netGB=3, perc_dij=40))

    #
    # Go mini (Vodafone)
    #  - 3000Ft
    #  - 100perc, 2GB
    #  - 40 Ft/perc
    elofizetesek.append(
        elofizetes(desc="Go mini", carrier="Vodafone", ingyen_percek=100,
                   alap_dij=3000, netGB=2, perc_dij=40))

    # Go Talk+(Vodafone)
    #  - 8000Ft
    #  - korlátlan beszéd
    #  - 2GB
    elofizetesek.append(
        elofizetes(desc="Go Talk+", carrier="Vodafone", ingyen_percek=math.inf,
                   alap_dij=8000, netGB=2))

    [print(e) for e in elofizetesek]
    return elofizetesek


def import_csv(fle: str):
    # return [tuple(x) for x in df.values]
    # return [[row[col] for col in df.columns] for row in df.to_dict('records')]
    return pd.read_csv(fle, delimiter=',').to_dict('records')


def get_callRecords(fle: str):
    return [callRecord(line) for line in import_csv(fle)]


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    elofizetesek = getElofizetesek()
    call_records = get_callRecords('./input/Report 2021.csv')

    # nr = phonenumbers.parse("+36201234567", None)
    # print("geocoder description_for_number: ", geocoder.description_for_number(nr, "hu"))
    # print("carrier name_for_number: ", carrier.name_for_number(nr, "hu"))
