"""
dwsim_export.py  —  DWSIM 9.0.5 flowsheet generator for EngineTools GT System
===============================================================================
Topology
  Feedwater  ──►  HRSG  ──►  Steam Header (free — needs splitter)
  Exhaust    ──►  HRSG  ──►  Stack Gas (free — no exhaust stream in this model)
  Steam→LiBr ──►  LiBr_HX  ──►  LiBr Condensate
  CHW Return ──►  LiBr_HX  ──►  CHW Supply
  Steam→MED  ──►  MED_HX   ──►  Fresh Water
  Seawater   ──►  MED_HX   ──►  Brine
  Cooling Tower, Steam Header : free (splitter not yet emitted)

HX port rule (from DWSIM reference):
  InputConnectors[0] + OutputConnectors[0]  = side A
  InputConnectors[1] + OutputConnectors[1]  = side B
  inlet & outlet of a side share the same port index.
"""
import copy, uuid
from datetime import datetime
import xml.etree.ElementTree as ET

_DWSIM_SAMPLES = "/Applications/DWSIM.app/Contents/MonoBundle/samples"
_HX_SAMPLE     = f"{_DWSIM_SAMPLES}/Heat Exchanger Sizing and Design.dwxml"
_SR_SAMPLE     = f"{_DWSIM_SAMPLES}/Hydrogen production through Methane Catalytic Steam Reforming.dwxml"

MW_W = 18.015e-3
BUILD_VERSION = "9.0.5.0"


def _uid():
    return str(uuid.uuid4()).upper()


def _hx_id():
    return "HE-" + str(uuid.uuid4()).lower()


def _load_templates():
    hx = ET.parse(_HX_SAMPLE).getroot()
    sr = ET.parse(_SR_SAMPLE).getroot()
    ms_tmpl = copy.deepcopy(hx.find('.//SimulationObject'))
    go_ms   = copy.deepcopy(hx.find('.//GraphicObjects/GraphicObject'))
    pp_tmpl = copy.deepcopy(
        next(pp for pp in hx.findall('.//PropertyPackages/PropertyPackage')
             if 'SteamTable' in (pp.findtext('Type') or '')))
    water_cp = copy.deepcopy(
        next(c for c in sr.find('Compounds') if c.findtext('CAS_Number') == '7732-18-5'))
    return ms_tmpl, go_ms, pp_tmpl, water_cp


# ── HeatExchanger SimulationObject ───────────────────────────────────────────
_HX_SIM_TMPL = """<SimulationObject>
<Type>DWSIM.UnitOperations.UnitOperations.HeatExchanger</Type>
<ObjectClass>Exchangers</ObjectClass>
<SupportsDynamicMode>true</SupportsDynamicMode>
<HasPropertiesForDynamicMode>true</HasPropertiesForDynamicMode>
<EquipmentTypes><Item></Item><Item>Shell and Tube</Item><Item>Plate and Frame</Item><Item>Double Pipe</Item></EquipmentTypes>
<IgnoreLMTDError>true</IgnoreLMTDError>
<CorrectionFactorLMTD>1</CorrectionFactorLMTD>
<HeatLoss>0</HeatLoss>
<OutletVaporFraction1>0</OutletVaporFraction1>
<OutletVaporFraction2>0</OutletVaporFraction2>
<PinchPointAtOutlets>false</PinchPointAtOutlets>
<UseShellAndTubeGeometryInformation>false</UseShellAndTubeGeometryInformation>
<CalculateHeatExchangeProfile>false</CalculateHeatExchangeProfile>
<STProperties>
<Type>DWSIM.UnitOperations.UnitOperations.Auxiliary.HeatExchanger.STHXProperties</Type>
<Shell_NumberOfShellsInSeries>1</Shell_NumberOfShellsInSeries>
<Shell_NumberOfPasses>2</Shell_NumberOfPasses>
<Shell_Di>500</Shell_Di><Shell_Fouling>0</Shell_Fouling>
<Shell_BaffleType>0</Shell_BaffleType><Shell_BaffleOrientation>1</Shell_BaffleOrientation>
<Shell_BaffleCut>20</Shell_BaffleCut><Shell_BaffleSpacing>250</Shell_BaffleSpacing>
<Shell_Fluid>1</Shell_Fluid>
<Tube_Di>50</Tube_Di><Tube_De>60</Tube_De><Tube_Length>5</Tube_Length>
<Tube_Fouling>0</Tube_Fouling><Tube_PassesPerShell>2</Tube_PassesPerShell>
<Tube_NumberPerShell>50</Tube_NumberPerShell><Tube_Layout>0</Tube_Layout>
<Tube_Pitch>70</Tube_Pitch><Tube_Fluid>0</Tube_Fluid>
<Tube_Roughness>0.045</Tube_Roughness><Shell_Roughness>0.045</Shell_Roughness>
<Tube_Scaling_FricCorrFactor>1.2</Tube_Scaling_FricCorrFactor>
<Tube_ThermalConductivity>70</Tube_ThermalConductivity>
<OverallFoulingFactor>0</OverallFoulingFactor>
<Ft>0</Ft><Fc>0</Fc><Fs>0</Fs><Ff>0</Ff><ReT>0</ReT><ReS>0</ReS>
</STProperties>
<LMTD_F>1</LMTD_F>
<FlowDir>CounterCurrent</FlowDir>
<DefinedTemperature>Cold_Fluid</DefinedTemperature>
<ThermalEfficiency>0</ThermalEfficiency>
<MaxHeatExchange>0</MaxHeatExchange>
<MITA>0</MITA>
<Efficiency>0</Efficiency>
<HeatDuty>0</HeatDuty>
<HotSideTemperatureChange>0</HotSideTemperatureChange>
<ColdSideTemperatureChange>0</ColdSideTemperatureChange>
<CalculationMode>CalcBothTemp_UA</CalculationMode>
<OverallCoefficient>1000</OverallCoefficient>
<Area>1</Area>
<DeltaP>0</DeltaP><Q>0</Q>
<HotSidePressureDrop>0</HotSidePressureDrop>
<ColdSidePressureDrop>0</ColdSidePressureDrop>
<HotSideOutletTemperature>298.15</HotSideOutletTemperature>
<ColdSideOutletTemperature>298.15</ColdSideOutletTemperature>
<LMTD>0</LMTD>
<MobileCompatible>true</MobileCompatible>
<ExternalSolverID></ExternalSolverID>
<ExternalSolverConfigData></ExternalSolverConfigData>
<ParticleSizeDistributions /><SupportsParticleSizeDistributions>false</SupportsParticleSizeDistributions>
<SupportsRestoreStateAfterError>true</SupportsRestoreStateAfterError>
<SelectedEquipmentType></SelectedEquipmentType>
<ComponentDescription>HeatExchanger</ComponentDescription>
<ComponentName>__NAME__</ComponentName>
<IsDirty>true</IsDirty>
<CanUsePreviousResults>false</CanUsePreviousResults>
<DynamicsSpec>Pressure</DynamicsSpec>
<DynamicsOnly>false</DynamicsOnly>
<Visible>true</Visible>
<OverrideCalculationRoutine>false</OverrideCalculationRoutine>
<StoreDetailedDebugReport>false</StoreDetailedDebugReport>
<IsFunctional>true</IsFunctional>
<PreferredFlashAlgorithmTag></PreferredFlashAlgorithmTag>
<Calculated>false</Calculated>
<DebugMode>false</DebugMode>
<LastUpdated>01/01/0001 00:00:00</LastUpdated>
<Annotation></Annotation>
<IsAdjustAttached>false</IsAdjustAttached>
<AttachedAdjustId></AttachedAdjustId>
<AdjustVarType>Manipulated</AdjustVarType>
<IsSpecAttached>false</IsSpecAttached>
<AttachedSpecId></AttachedSpecId>
<SpecVarType>Source</SpecVarType>
<Name>__NAME__</Name>
<UserDefinedChartNames />
<ProductName>Heat Exchanger</ProductName>
<ProductDescription>Rigorous Heat Exchanger model</ProductDescription>
<ProductAuthor>Daniel Wagner</ProductAuthor>
<ProductContactInfo>https://dwsim.inforside.com.br</ProductContactInfo>
<ProductPage>https://dwsim.inforside.com.br</ProductPage>
<ProductVersion>9.0.5.0</ProductVersion>
<ProductAssembly>DWSIM.SharedClasses</ProductAssembly>
<IsSource>false</IsSource>
<IsSink>false</IsSink>
<DynamicProperties>
<Property><Name>Cold Fluid Flow Conductance</Name><PropertyType>System.Double</PropertyType><Data>1.0</Data></Property>
<Property><Name>Hot Fluid Flow Conductance</Name><PropertyType>System.Double</PropertyType><Data>1.0</Data></Property>
<Property><Name>Volume for Cold Fluid</Name><PropertyType>System.Double</PropertyType><Data>1.0</Data></Property>
<Property><Name>Volume for Hot Fluid</Name><PropertyType>System.Double</PropertyType><Data>1.0</Data></Property>
<Property><Name>Cold Side Pressure</Name><PropertyType>System.Double</PropertyType><Data>101325.0</Data></Property>
<Property><Name>Hot Side Pressure</Name><PropertyType>System.Double</PropertyType><Data>101325.0</Data></Property>
<Property><Name>Minimum Pressure</Name><PropertyType>System.Double</PropertyType><Data>101325.0</Data></Property>
<Property><Name>Initialize using Inlet Streams</Name><PropertyType>System.Double</PropertyType><Data>0.0</Data></Property>
<Property><Name>Reset Contents</Name><PropertyType>System.Double</PropertyType><Data>0.0</Data></Property>
</DynamicProperties>
<DynamicPropertiesDescriptions>
<Property><Name>Cold Fluid Flow Conductance</Name><PropertyType>System.String</PropertyType><Data>"Flow Conductance for Cold Fluid."</Data></Property>
<Property><Name>Hot Fluid Flow Conductance</Name><PropertyType>System.String</PropertyType><Data>"Flow Conductance for Hot Fluid."</Data></Property>
<Property><Name>Volume for Cold Fluid</Name><PropertyType>System.String</PropertyType><Data>"Volume for Cold Fluid"</Data></Property>
<Property><Name>Volume for Hot Fluid</Name><PropertyType>System.String</PropertyType><Data>"Volume for Hot Fluid"</Data></Property>
<Property><Name>Cold Side Pressure</Name><PropertyType>System.String</PropertyType><Data>"Dynamic Pressure Cold Fluid."</Data></Property>
<Property><Name>Hot Side Pressure</Name><PropertyType>System.String</PropertyType><Data>"Dynamic Pressure Hot Fluid."</Data></Property>
<Property><Name>Minimum Pressure</Name><PropertyType>System.String</PropertyType><Data>"Minimum Dynamic Pressure."</Data></Property>
<Property><Name>Initialize using Inlet Streams</Name><PropertyType>System.String</PropertyType><Data>"Initialize from inlet streams."</Data></Property>
<Property><Name>Reset Contents</Name><PropertyType>System.String</PropertyType><Data>"Empty volume contents."</Data></Property>
</DynamicPropertiesDescriptions>
<DynamicPropertiesUnitTypes>
<Property><Name>Cold Fluid Flow Conductance</Name><PropertyType>DWSIM.Interfaces.Enums.UnitOfMeasure</PropertyType><Data>67</Data></Property>
<Property><Name>Hot Fluid Flow Conductance</Name><PropertyType>DWSIM.Interfaces.Enums.UnitOfMeasure</PropertyType><Data>67</Data></Property>
<Property><Name>Volume for Cold Fluid</Name><PropertyType>DWSIM.Interfaces.Enums.UnitOfMeasure</PropertyType><Data>63</Data></Property>
<Property><Name>Volume for Hot Fluid</Name><PropertyType>DWSIM.Interfaces.Enums.UnitOfMeasure</PropertyType><Data>63</Data></Property>
<Property><Name>Cold Side Pressure</Name><PropertyType>DWSIM.Interfaces.Enums.UnitOfMeasure</PropertyType><Data>46</Data></Property>
<Property><Name>Hot Side Pressure</Name><PropertyType>DWSIM.Interfaces.Enums.UnitOfMeasure</PropertyType><Data>46</Data></Property>
<Property><Name>Minimum Pressure</Name><PropertyType>DWSIM.Interfaces.Enums.UnitOfMeasure</PropertyType><Data>46</Data></Property>
<Property><Name>Initialize using Inlet Streams</Name><PropertyType>DWSIM.Interfaces.Enums.UnitOfMeasure</PropertyType><Data>66</Data></Property>
<Property><Name>Reset Contents</Name><PropertyType>DWSIM.Interfaces.Enums.UnitOfMeasure</PropertyType><Data>66</Data></Property>
</DynamicPropertiesUnitTypes>
<AttachedUtilities />
<PropertyPackage></PropertyPackage>
</SimulationObject>"""


def _conn_el(is_attached, conn_type=None, other_id=None, other_idx=0, energy=False):
    """Build a Connector element."""
    c = ET.Element("Connector")
    c.set("IsAttached", "true" if is_attached else "false")
    if is_attached:
        c.set("ConnType",         conn_type)
        key = "AttachedFromObjID" if conn_type == "ConIn" else "AttachedToObjID"
        idx = "AttachedFromConnIndex" if conn_type == "ConIn" else "AttachedToConnIndex"
        ek  = "AttachedFromEnergyConn" if conn_type == "ConIn" else "AttachedToEnergyConn"
        c.set(key,  other_id)
        c.set(idx,  str(other_idx))
        c.set(ek,   "True" if energy else "False")
    return c


def _hx_sim(hx_id, tag):
    """Return HX SimulationObject ET.Element."""
    xml = _HX_SIM_TMPL.replace("__NAME__", hx_id)
    el  = ET.fromstring(xml)
    # Set Tag
    tag_el = ET.SubElement(el, "Tag"); tag_el.text = tag
    return el


def _hx_go(hx_id, tag, x, y,
           in0_id=None, in1_id=None,
           out0_id=None, out1_id=None):
    """Return HX GraphicObject ET.Element with wired connectors."""
    go = ET.Element("GraphicObject")
    for k, v in [
        ("Type",   "DWSIM.Drawing.SkiaSharp.GraphicObjects.Shapes.HeatExchangerGraphic"),
        ("SemiTransparent","false"),("LineWidth","1"),("GradientMode","true"),
        ("LineColor","#fffa8072"),("LineColorDark","#fff5f5f5"),
        ("Fill","true"),("FillColor","#ffd3d3d3"),("FillColorDark","#ffffffff"),
        ("GradientColor1","#ffd3d3d3"),("GradientColor2","#ffffffff"),
        ("FontSize","10"),("OverrideColors","false"),("FontStyle","Bold"),
        ("Calculated","false"),("Active","true"),("Description","Heat Exchanger"),
        ("FlippedH","false"),("FlippedV","false"),("IsEnergyStream","false"),
        ("ObjectType","HeatExchanger"),("Shape","0"),("ShapeOverride","DefaultShape"),
        ("Status","NotCalculated"),("AutoSize","false"),
        ("Height","30"),("IsConnector","false"),
        ("Name",hx_id),("Tag",tag),("Width","30"),
        ("X",str(float(x))),("Y",str(float(y))),
        ("Selected","false"),("Rotation","0"),("DrawMode","0"),("DrawLabel","true"),
    ]:
        ET.SubElement(go, k).text = v

    ic = ET.SubElement(go, "InputConnectors")
    ic.append(_conn_el(in0_id is not None, "ConIn",  in0_id,  0))
    ic.append(_conn_el(in1_id is not None, "ConIn",  in1_id,  0))

    oc = ET.SubElement(go, "OutputConnectors")
    oc.append(_conn_el(out0_id is not None, "ConOut", out0_id, 0))
    oc.append(_conn_el(out1_id is not None, "ConOut", out1_id, 0))

    ET.SubElement(ET.SubElement(go, "EnergyConnector"), "Connector").set("IsAttached","false")
    ET.SubElement(go, "SpecialConnectors")
    return go


def _build_stream(ms_tmpl, sid, tag, T_K, P_Pa, h_kj_kg,
                  mflow_kgs, pp_id, vapor=False,
                  out_to_hx=None, out_to_hx_port=0,   # stream output → HX input
                  in_from_hx=None, in_from_hx_port=0): # stream input ← HX output
    """Clone template stream, set values, wire both connector ends."""
    ms  = copy.deepcopy(ms_tmpl)
    mol = mflow_kgs / MW_W
    rho = 5.0 if vapor else 990.0
    now = datetime.now().strftime("%m/%d/%Y %H:%M:%S")

    for t in ("ComponentDescription","ComponentName","Name2","Name"):
        e = ms.find(t)
        if e is not None: e.text = sid
    tag_el = ms.find("Tag")
    if tag_el is None: tag_el = ET.SubElement(ms, "Tag")
    tag_el.text = tag

    pp_ref = ms.find("PropertyPackage")
    if pp_ref is not None: pp_ref.text = pp_id

    # Set phase properties
    _PH = {0:"Mixture",1:"VaporLiquid",2:"Liquid1",3:"Liquid2",
           4:"Liquid3",5:"Solid",6:"Vapor",7:"Aqueous"}
    phases = ms.find("Phases")
    for i, ph in enumerate(phases):
        pname = ph.find("ComponentName")
        if pname is not None: pname.text = _PH.get(i,"Phase")
        nname = ph.find("Name")
        if nname is not None: nname.text = _PH.get(i,"Phase")

        comps = [c for c in ph if c.tag == "Compounds"]
        if comps:
            for c in list(comps[0]): comps[0].remove(c)
            w = ET.SubElement(comps[0], "Compound")
            for k, v in [("Type","DWSIM.Thermodynamics.BaseClasses.Compound"),
                         ("ComponentDescription",""),("ComponentName","Water"),
                         ("ActivityCoeff","0"),("PetroleumFraction","false"),
                         ("MassFraction","1.0"),("MoleFraction","1.0"),
                         ("Molarity","0"),("Molality","0"),("FugacityCoeff","0"),
                         ("Kvalue","NaN"),("lnKvalue","NaN"),
                         ("MassFlow","0"),("MolarFlow","0"),("Name","Water"),
                         ("PartialPressure","0"),("PartialVolume","0"),
                         ("VolumetricFlow","0"),("VolumetricFraction","0"),
                         ("DiffusionCoefficient","Infinity"),
                         ("EnthalpyF_Dmol","0"),("EntropyF_Dmol","0")]:
                ET.SubElement(w, k).text = v
            ET.SubElement(w, "DynamicProperties")
            if i == 0 or (i == 6 and vapor) or (i == 2 and not vapor):
                w.find("MassFlow").text  = str(mflow_kgs)
                w.find("MolarFlow").text = str(mol)

        props_list = [c for c in ph if c.tag == "Properties" and len(list(c)) > 0]
        for props in props_list:
            def _s(tag_, val):
                e = props.find(tag_)
                if e is None: e = ET.SubElement(props, tag_)
                e.text = str(val)
            if i == 0:
                _s("temperature", T_K); _s("pressure", P_Pa)
                _s("enthalpy", h_kj_kg); _s("massflow", mflow_kgs)
                _s("molarflow", mol); _s("density", rho); _s("entropy","0")
            elif (i==6 and vapor) or (i==2 and not vapor):
                _s("temperature", T_K); _s("pressure", P_Pa)
                _s("enthalpy", h_kj_kg); _s("massflow", mflow_kgs)
                _s("molarflow", mol); _s("massfraction","1")
            else:
                for t_ in ("temperature","pressure","enthalpy","massflow",
                           "molarflow","massfraction","density"):
                    _s(t_, "0")

    return ms


def _build_stream_go(go_tmpl, sid, tag, x, y,
                     out_to_hx=None, out_to_hx_port=0,
                     in_from_hx=None, in_from_hx_port=0):
    """Build stream GraphicObject with fully mirrored connector wiring."""
    go = copy.deepcopy(go_tmpl)

    for k in ("Name",):
        e = go.find(k)
        if e is not None: e.text = sid
    for k in ("Tag","Description"):
        e = go.find(k)
        if e is not None: e.text = tag
    for k, v in [("X",str(float(x))),("Y",str(float(y)))]:
        e = go.find(k)
        if e is not None: e.text = v

    # Clear and rebuild connectors
    for block_tag in ("InputConnectors","OutputConnectors","EnergyConnector","SpecialConnectors"):
        block = go.find(block_tag)
        if block is not None:
            for c in list(block): block.remove(c)
        else:
            block = ET.SubElement(go, block_tag)

    ic = go.find("InputConnectors")
    oc = go.find("OutputConnectors")
    ec = go.find("EnergyConnector")

    # Input connector: wired if this stream receives output FROM a HX
    if in_from_hx:
        ic.append(_conn_el(True, "ConIn", in_from_hx, in_from_hx_port))
    else:
        ic.append(_conn_el(False))

    # Output connector: wired if this stream feeds INTO a HX
    if out_to_hx:
        oc.append(_conn_el(True, "ConOut", out_to_hx, out_to_hx_port))
    else:
        oc.append(_conn_el(False))

    ec.append(_conn_el(False))
    return go


def build_gt_flowsheet(engine, values: dict, result: dict) -> str:
    r, v   = result, values
    now    = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    pp_id  = _uid()

    ms_tmpl, go_ms_tmpl, pp_tmpl, water_cp = _load_templates()

    # ── IDs ───────────────────────────────────────────────────────────────────
    # Streams
    S = {k: _uid() for k in ["FW","ST","SL","SM","CL","CS","CR","SW","DW","BR","CT"]}
    # Heat Exchangers
    HX = {k: _hx_id() for k in ["HRSG","LIBR","MED"]}

    # ── Root ──────────────────────────────────────────────────────────────────
    root = ET.Element("DWSIM_Simulation_Data")
    gi   = ET.SubElement(root, "GeneralInfo")
    for k, val in [("BuildVersion", BUILD_VERSION),("BuildDate","2000-01-01T00:00:00"),
                   ("SavedOn",now),("GeneratedBy","EngineTools — Nexa Block v1"),
                   ("ToolName",engine.name),("SavedFromClassicUI","false")]:
        ET.SubElement(gi, k).text = val

    sett = ET.SubElement(root, "Settings")
    notes = (f"EngineTools — {engine.name}\n"
             f"GT: {r['p_gt']:.0f} kW | NG: {r['ng_nm3ph']:.0f} Nm3/h\n"
             f"Steam: {r['m_steam_tph']:.2f} t/h @ {v['steam_p_bar']:.0f}bar/{r['t_steam_c']:.0f}C\n"
             f"LiBr: {r['q_libr_cool_kw']:.0f} kW ({r['q_libr_cool_tr']:.0f}TR)\n"
             f"Fresh Water: {r['m_dist_m3pd']:.0f} m3/day")
    for k, val in [("SimulationName",engine.name),("FlowsheetNotes",notes),
                   ("SelectedCompounds","Water"),
                   ("UsePropertyPackageForSurface","false"),        # NO BackColor
                   ("MassFlowUnit","kg/s"),("EnergyUnit","kW"),
                   ("TemperatureUnit","K"),("PressureUnit","Pa"),
                   ("MassEnthalyUnit","kJ/kg"),("DensityUnit","kg/m3")]:
        ET.SubElement(sett, k).text = val

    comps = ET.SubElement(root, "Compounds")
    comps.append(copy.deepcopy(water_cp))

    pps = ET.SubElement(root, "PropertyPackages")
    pp  = copy.deepcopy(pp_tmpl)
    id_el = pp.find("ID")
    if id_el is not None: id_el.text = pp_id
    pps.append(pp)

    sim      = ET.SubElement(root, "SimulationObjects")
    graphics = ET.SubElement(root, "GraphicObjects")

    # ── Helper values ─────────────────────────────────────────────────────────
    p_st  = v["steam_p_bar"]; t_st = r["t_steam_c"]; h_sh = r["h_steam_kj"]
    fw_t  = v["fw_t_c"]
    def ms(tph): return tph * 1000 / 3600
    def hf(tc):  return 4.19 * tc

    # ── Add unit operations ───────────────────────────────────────────────────
    # HRSG: side A = FW in / Steam out; side B = free (no exhaust stream)
    sim.append(_hx_sim(HX["HRSG"], "HRSG"))
    graphics.append(_hx_go(HX["HRSG"], "HRSG", 240, 280,
                            in0_id=S["FW"],   in1_id=None,
                            out0_id=S["ST"],  out1_id=None))

    # LiBr HX: side A = Steam→LiBr in / LiBr Cond out; side B = CHW Return in / CHW Supply out
    sim.append(_hx_sim(HX["LIBR"], "LiBr Chiller"))
    graphics.append(_hx_go(HX["LIBR"], "LiBr Chiller", 720, 200,
                            in0_id=S["SL"],   in1_id=S["CR"],
                            out0_id=S["CL"],  out1_id=S["CS"]))

    # MED HX: side A = Steam→MED in / Fresh Water out; side B = Seawater in / Brine out
    sim.append(_hx_sim(HX["MED"], "MED Desalination"))
    graphics.append(_hx_go(HX["MED"], "MED Desalination", 720, 380,
                            in0_id=S["SM"],   in1_id=S["SW"],
                            out0_id=S["DW"],  out1_id=S["BR"]))

    # ── Stream definitions with wiring ────────────────────────────────────────
    # (sid, tag, T_K, P_Pa, h, mflow_kgs, vapor,  out→HX, out_port, in←HX, in_port)
    p_st_pa = p_st * 1e5
    stream_specs = [
        # Feedwater: output → HRSG inlet 0
        ("FW", f"Feedwater ({fw_t:.0f}°C)",    fw_t+273.15, p_st_pa, hf(fw_t), ms(r["m_steam_tph"]), False,
         HX["HRSG"], 0,  None,        0),
        # Steam Header: input ← HRSG outlet 0; free output (needs splitter)
        ("ST", f"Steam {p_st:.0f}bar/{t_st:.0f}°C", t_st+273.15, p_st_pa, h_sh, ms(r["m_steam_tph"]), True,
         None, 0,  HX["HRSG"],  0),
        # Steam→LiBr: output → LiBr HX inlet 0
        ("SL", f"Steam→LiBr {r['m_libr_tph']:.2f}t/h", t_st+273.15, p_st_pa, h_sh, ms(r["m_libr_tph"]), True,
         HX["LIBR"], 0,  None,        0),
        # Steam→MED: output → MED HX inlet 0
        ("SM", f"Steam→MED {r['m_med_tph']:.2f}t/h",   t_st+273.15, p_st_pa, h_sh, ms(r["m_med_tph"]), True,
         HX["MED"],  0,  None,        0),
        # LiBr Condensate: input ← LiBr HX outlet 0
        ("CL", "LiBr Condensate (100°C)",       373.15, 101325.0, hf(100), ms(r["m_libr_tph"]), False,
         None, 0,  HX["LIBR"],  0),
        # CHW Supply: input ← LiBr HX outlet 1
        ("CS", f"CHW Supply ({v['chw_sup_c']:.0f}°C)", v["chw_sup_c"]+273.15, 3e5, hf(v["chw_sup_c"]), r["chw_m3ph"]*1000/3600, False,
         None, 0,  HX["LIBR"],  1),
        # CHW Return: output → LiBr HX inlet 1
        ("CR", f"CHW Return ({v['chw_sup_c']+v['chw_dt_c']:.0f}°C)",
               v["chw_sup_c"]+v["chw_dt_c"]+273.15, 3e5,
               hf(v["chw_sup_c"]+v["chw_dt_c"]), r["chw_m3ph"]*1000/3600, False,
         HX["LIBR"], 1,  None,        0),
        # Seawater: output → MED HX inlet 1
        ("SW", f"Seawater ({v['sw_t_c']:.0f}°C)", v["sw_t_c"]+273.15, 1.5e5, hf(v["sw_t_c"]), r["m_sw_m3ph"]*1020/3600, False,
         HX["MED"],  1,  None,        0),
        # Fresh Water: input ← MED HX outlet 0
        ("DW", f"Fresh Water ({r['m_dist_m3pd']:.0f} m3/day)", 313.15, 101325.0, hf(40), r["m_dist_m3ph"]*1000/3600, False,
         None, 0,  HX["MED"],   0),
        # Brine: input ← MED HX outlet 1
        ("BR", f"Brine ({r['m_brine_m3ph']:.1f} m3/h)", 333.15, 101325.0, hf(60), r["m_brine_m3ph"]*1030/3600, False,
         None, 0,  HX["MED"],   1),
        # Cooling Tower: free (no HX yet)
        ("CT", f"Cooling Tower ({r['ct_m3ph']:.1f} m3/h)", 303.15, 3e5, hf(30), r["ct_m3ph"]*1000/3600, False,
         None, 0,  None,        0),
    ]

    # Canvas layout positions
    layout = {
        "FW":( 80,280), "ST":(400,280),
        "SL":(540,200), "SM":(540,380),
        "CL":(900,200), "CS":(1060,140), "CR":(1060,240),
        "SW":(900,380), "DW":(1060,320), "BR":(1060,420),
        "CT":(900,280),
    }

    for (k, tag, T_K, P_Pa, h, mf, vap, oth, op, ifh, ip) in stream_specs:
        sid = S[k]
        # SimulationObject
        so = _build_stream(ms_tmpl, sid, tag, T_K, P_Pa, h, mf, pp_id, vap,
                           out_to_hx=oth, out_to_hx_port=op,
                           in_from_hx=ifh, in_from_hx_port=ip)
        sim.append(so)
        # GraphicObject
        x, y = layout[k]
        go = _build_stream_go(go_ms_tmpl, sid, tag, x, y,
                               out_to_hx=oth, out_to_hx_port=op,
                               in_from_hx=ifh, in_from_hx_port=ip)
        graphics.append(go)

    for tag in ["ReactionSets","Reactions","StoredSolutions","DynamicsManager",
                "WatchItems","ScriptItems","ChartItems","MessagesLog"]:
        ET.SubElement(root, tag)

    ET.indent(root)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")


def build_flowsheet(engine, values: dict, result: dict) -> str:
    if "gas_turbine" in engine.key or "gt" in engine.name.lower():
        return build_gt_flowsheet(engine, values, result)
    raise ValueError(f"No DWSIM flowsheet builder for: {engine.name}")
