/**
 * Google Apps Script para sincronizar a planilha Ploomes_Clientes com o Ploomes.
 *
 * Classificação por estrutura da linha, sem depender de B2C, marcador ou categoria:
 * - Razão Social - Empresa preenchida, Nome - Pessoa vazio: cria empresa.
 * - Razão Social - Empresa preenchida, Nome - Pessoa preenchido: cria empresa e pessoa vinculada.
 * - Razão Social - Empresa vazia, Nome - Pessoa preenchido: cria pessoa física sem empresa.
 *
 * Como usar:
 * 1. Abra a planilha no Google Sheets.
 * 2. Extensões > Apps Script.
 * 3. Cole este arquivo como Code.gs.
 * 4. Rode configurarPloomesApiKey e cole a User-Key.
 * 5. Rode prepararPlanilha.
 * 6. Rode simularEnvioPloomes se quiser ver uma prévia dos payloads.
 * 7. Rode enviarAoPloomes para refletir a planilha no CRM.
 * 8. Use importarDoPloomes ou sincronizarBidirecionalPloomes para manter sheet e Ploomes coerentes nos dois sentidos.
 */

const CONFIG = {
  SHEET_NAME: 'Clientes',
  API_BASE: 'https://api2.ploomes.com',
  MAX_ROWS_PER_RUN: 25,
  REQUEST_SLEEP_MS: 650,
  UPDATE_EXISTING: true,
  COMPARE_BEFORE_UPDATE: true,
  SYNC_SENT_ROWS: true,
  REQUIRE_SEND_FLAG: false,
  PULL_PAGE_SIZE: 100,
  SPREADSHEET_ID: '1cMzEfzHgn50QUjgNww8eqJIIgX6F-G8wskI8R1DzrnU',
  CONTROL_COLUMNS: [
    'Tipo Detectado',
    'Status Importação',
    'Ploomes Id Empresa',
    'Ploomes Id Pessoa',
    'Erro Importação',
    'Última sincronização'
  ]
};

const STATUS = {
  READY: 'SIM',
  SENT: 'Enviado',
  ERROR: 'Erro',
  DRY_RUN: 'Simulado',
  SKIPPED: 'Ignorado'
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Ploomes')
    .addItem('Configurar API key', 'configurarPloomesApiKey')
    .addItem('Preparar colunas', 'prepararPlanilha')
    .addSeparator()
    .addItem('Importar do Ploomes', 'importarDoPloomes')
    .addItem('Sincronizar bidirecional', 'sincronizarBidirecionalPloomes')
    .addSeparator()
    .addItem('Simular envio', 'simularEnvioPloomes')
    .addItem('Enviar linhas elegíveis', 'enviarAoPloomes')
    .addSeparator()
    .addItem('Instalar gatilho a cada 15 min', 'instalarGatilhoPloomes')
    .addItem('Remover gatilhos', 'removerGatilhosPloomes')
    .addItem('Diagnosticar linhas', 'diagnosticarPloomes')
    .addToUi();
}

function configurarPloomesApiKey() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.prompt(
    'Ploomes API key',
    'Cole a User-Key do Ploomes. Ela ficará salva em Script Properties, não na planilha.',
    ui.ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() !== ui.Button.OK) return;

  const key = clean(response.getResponseText());
  if (!key) {
    ui.alert('Chave vazia. Nada foi salvo.');
    return;
  }

  PropertiesService.getScriptProperties().setProperty('PLOOMES_API_KEY', key);
  ui.alert('API key salva.');
}

function configurarPloomesApiKeyHeadless(apiKey) {
  const key = clean(apiKey);
  if (!key) throw new Error('PLOOMES_API_KEY vazia.');
  PropertiesService.getScriptProperties().setProperty('PLOOMES_API_KEY', key);
  return 'PLOOMES_API_KEY salva.';
}

function configurarPlanilhaPloomesHeadless(spreadsheetId) {
  const id = clean(spreadsheetId);
  if (!id) throw new Error('PLOOMES_SPREADSHEET_ID vazio.');
  PropertiesService.getScriptProperties().setProperty('PLOOMES_SPREADSHEET_ID', id);
  return `PLOOMES_SPREADSHEET_ID salvo: ${id}`;
}

function prepararPlanilha() {
  const sheet = getSheet_();
  const headerMap = ensureControlColumns_(sheet);
  const values = sheet.getDataRange().getValues();

  for (let rowIndex = 1; rowIndex < values.length; rowIndex++) {
    const row = rowObject_(values[rowIndex], headerMap);
    const kind = rowKind_(row);
    sheet.getRange(rowIndex + 1, headerMap['Tipo Detectado'] + 1).setValue(kind);
  }

  return notify_('Colunas preparadas e Tipo Detectado atualizado.');
}

function enviarLinhasEspecificasPloomes(rowNumbers) {
  const parsed = Array.isArray(rowNumbers) ? rowNumbers.map(Number).filter(Number.isFinite) : [];
  if (!parsed.length) throw new Error('Forneça um array de números de linha, por exemplo [66,67,68].');
  return syncPloomes_({ dryRun: false, onlyRows: parsed });
}

function enviarLinhasSemIdsPloomes() {
  const sheet = getSheet_();
  const headerMap = ensureControlColumns_(sheet);
  const values = sheet.getDataRange().getValues();
  const rows = [];
  for (let rowIndex = 1; rowIndex < values.length; rowIndex++) {
    const row = rowObject_(values[rowIndex], headerMap);
    const kind = rowKind_(row);
    const companyId = clean(row['Ploomes Id Empresa']);
    const personId = clean(row['Ploomes Id Pessoa']);
    if (kind !== 'ignorar' && !companyId && !personId) rows.push(rowIndex + 1);
  }
  if (!rows.length) return notify_('Nenhuma linha válida sem IDs do Ploomes.');
  return syncPloomes_({ dryRun: false, onlyRows: rows });
}

function simularEnvioPloomes() {
  syncPloomes_({ dryRun: true });
}

function enviarAoPloomes() {
  syncPloomes_({ dryRun: false });
}

function instalarGatilhoPloomes() {
  removerGatilhosPloomes();
  ScriptApp.newTrigger('enviarAoPloomes')
    .timeBased()
    .everyMinutes(15)
    .create();
  SpreadsheetApp.getUi().alert('Gatilho instalado para rodar a cada 15 minutos.');
}

function removerGatilhosPloomes() {
  ScriptApp.getProjectTriggers().forEach(trigger => {
    if (trigger.getHandlerFunction() === 'enviarAoPloomes') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function sincronizarBidirecionalPloomes() {
  importarDoPloomes();
  enviarAoPloomes();
}

function diagnosticarPloomes() {
  const apiKey = getApiKey_();
  const sheet = getSheet_();
  const headerMap = ensureControlColumns_(sheet);
  const values = sheet.getDataRange().getValues();
  const crmCompanies = fetchAllContacts_(apiKey, 1);
  const crmPeople = fetchAllContacts_(apiKey, 2);

  const counts = {
    totalDataRows: Math.max(values.length - 1, 0),
    sheetCompanyOnly: 0,
    sheetCompanyWithPerson: 0,
    sheetPersonOnly: 0,
    ignoredNoNames: 0,
    exportValidRows: 0,
    exportRowsLinkedToPloomes: 0,
    exportRowsWithoutIds: 0,
    exportRowsWithErrorStatus: 0,
    exportRowsAlreadySent: 0
  };

  const sheetCompanyIds = new Set();
  const sheetPersonIds = new Set();

  for (let rowIndex = 1; rowIndex < values.length; rowIndex++) {
    const row = rowObject_(values[rowIndex], headerMap);
    const currentStatus = clean(row['Status Importação']);
    const kind = rowKind_(row);
    const companyId = clean(row['Ploomes Id Empresa']);
    const personId = clean(row['Ploomes Id Pessoa']);

    if (companyId) sheetCompanyIds.add(companyId);
    if (personId) sheetPersonIds.add(personId);

    if (kind === 'empresa_sem_pessoa') counts.sheetCompanyOnly++;
    else if (kind === 'empresa_com_pessoa') counts.sheetCompanyWithPerson++;
    else if (kind === 'pessoa_fisica_sem_empresa') counts.sheetPersonOnly++;
    else counts.ignoredNoNames++;

    if (kind !== 'ignorar') {
      counts.exportValidRows++;
      if (companyId || personId) counts.exportRowsLinkedToPloomes++;
      else counts.exportRowsWithoutIds++;
      if (currentStatus === STATUS.SENT) counts.exportRowsAlreadySent++;
      if (currentStatus === STATUS.ERROR) counts.exportRowsWithErrorStatus++;
    }
  }

  const missingCompanies = crmCompanies.filter(company => !sheetCompanyIds.has(String(company.Id))).length;
  const missingPeople = crmPeople.filter(person => !sheetPersonIds.has(String(person.Id))).length;

  const msg = [
    'Importáveis do Ploomes',
    `- Empresas no CRM: ${crmCompanies.length}`,
    `- Pessoas no CRM: ${crmPeople.length}`,
    `- Empresas ainda ausentes na planilha: ${missingCompanies}`,
    `- Pessoas ainda ausentes na planilha: ${missingPeople}`,
    '',
    'Exportáveis para o Ploomes',
    `- Linhas válidas na planilha: ${counts.exportValidRows}`,
    `- Linhas já ligadas a IDs do Ploomes: ${counts.exportRowsLinkedToPloomes}`,
    `- Linhas ainda sem IDs do Ploomes: ${counts.exportRowsWithoutIds}`,
    `- Linhas com Status Importação = Enviado: ${counts.exportRowsAlreadySent}`,
    `- Linhas com Status Importação = Erro: ${counts.exportRowsWithErrorStatus}`,
    '',
    'Composição da planilha',
    `- Linhas de dados: ${counts.totalDataRows}`,
    `- Empresa sem pessoa: ${counts.sheetCompanyOnly}`,
    `- Empresa com pessoa: ${counts.sheetCompanyWithPerson}`,
    `- Pessoa sem empresa: ${counts.sheetPersonOnly}`,
    `- Sem Razão Social - Empresa e sem Nome - Pessoa: ${counts.ignoredNoNames}`,
    '',
    'Observação',
    '- A coluna Enviar ao Ploomes? foi descontinuada e saiu do cálculo canônico do sync two way.'
  ].join('\n');

  return notify_(msg);
}

function isRowEligible_(kind, currentStatus) {
  if (kind === 'ignorar') return false;
  if (currentStatus === STATUS.SENT && !CONFIG.SYNC_SENT_ROWS) return false;
  return true;
}

function notify_(message) {
  try {
    SpreadsheetApp.getUi().alert(message);
  } catch (error) {
    Logger.log(message);
  }
  return message;
}

function syncPloomes_({ dryRun, onlyRows }) {
  const selectedRows = Array.isArray(onlyRows) ? new Set(onlyRows.map(Number)) : null;
  const sheet = getSheet_();
  const headerMap = ensureControlColumns_(sheet);
  const values = sheet.getDataRange().getValues();
  const apiKey = getApiKey_();
  const now = new Date();

  let processed = 0;
  let sent = 0;
  let errors = 0;
  let skipped = 0;

  const originByName = loadOrigins_(apiKey);

  for (let rowIndex = 1; rowIndex < values.length; rowIndex++) {
    if (processed >= CONFIG.MAX_ROWS_PER_RUN) break;

    const sheetRow = rowIndex + 1;
    if (selectedRows && !selectedRows.has(sheetRow)) continue;

    const row = rowObject_(values[rowIndex], headerMap);
    const currentStatus = clean(row['Status Importação']);
    const kind = rowKind_(row);

    if (!isRowEligible_(kind, currentStatus)) continue;

    processed++;
    setCell_(sheet, sheetRow, headerMap, 'Tipo Detectado', kind);

    try {
      if (kind === 'ignorar') {
        skipped++;
        writeStatus_(sheet, sheetRow, headerMap, STATUS.SKIPPED, '', '', 'Linha sem Razão Social - Empresa e sem Nome - Pessoa.', now);
        continue;
      }

      const plan = buildPlan_(row, kind, originByName);
      validatePlan_(plan);

      if (dryRun) {
        const companyPreview = plan.company ? JSON.stringify(plan.company) : '';
        const personPreview = plan.person ? JSON.stringify(plan.person) : '';
        writeStatus_(sheet, sheetRow, headerMap, STATUS.DRY_RUN, companyPreview, personPreview, '', now);
        sent++;
        continue;
      }

      let companyId = '';
      let personId = '';

      if (plan.company) {
        const companyResult = createOrUpdateContact_(apiKey, plan.company, findCompany_);
        companyId = companyResult.id;
      }

      if (plan.person) {
        const personPayload = Object.assign({}, plan.person);
        if (kind === 'empresa_com_pessoa') {
          if (!companyId) throw new Error('Empresa não retornou Id para vincular pessoa.');
          personPayload.CompanyId = Number(companyId);
        }
        validatePersonPayload_(personPayload, kind);
        const personResult = createOrUpdateContact_(apiKey, personPayload, findPerson_);
        personId = personResult.id;
      }

      writeStatus_(sheet, sheetRow, headerMap, STATUS.SENT, companyId, personId, '', now);
      sent++;
      Utilities.sleep(CONFIG.REQUEST_SLEEP_MS);
    } catch (error) {
      errors++;
      writeStatus_(sheet, sheetRow, headerMap, STATUS.ERROR, '', '', String(error && error.message ? error.message : error), now);
    }
  }

  const msg = `Processadas: ${processed}\nOK/simuladas: ${sent}\nIgnoradas: ${skipped}\nErros: ${errors}`;
  return notify_(msg);
}


function buildPlan_(row, kind, originByName) {
  if (kind === 'empresa_sem_pessoa') {
    return { kind, company: buildCompanyPayload_(row, originByName), person: null };
  }
  if (kind === 'empresa_com_pessoa') {
    return { kind, company: buildCompanyPayload_(row, originByName), person: buildPersonPayload_(row, originByName) };
  }
  if (kind === 'pessoa_fisica_sem_empresa') {
    return { kind, company: null, person: buildPersonPayload_(row, originByName) };
  }
  return { kind, company: null, person: null };
}

function buildCompanyPayload_(row, originByName) {
  const name = companyName_(row);
  if (!name) return null;

  const payload = {
    TypeId: 1,
    Name: name,
    LegalName: name
  };

  const cnpj = onlyDigits_(pick_(row, 'CNPJ - Empresa', 'CNPJ'));
  const site = pick_(row, 'Site', 'Site - Empresa');
  const originId = originId_(row, originByName);
  const note = joinedNote_(
    fieldNote_('Segmento', pick_(row, 'Segmento de atuação - Empresa', 'Segmento - Empresa')),
    fieldNote_('Estado', pick_(row, 'Estado - Empresa')),
    fieldNote_('Cidade', pick_(row, 'Cidade - Empresa')),
    fieldNote_('Marcadores', pick_(row, 'Marcadores - Empresa', 'Marcadores')),
    pick_(row, 'Relação', 'Relacao'),
    pick_(row, 'Observações', 'Observacoes')
  );

  if (cnpj) payload.Register = cnpj;
  if (site) payload.Website = site;
  if (originId) payload.OriginId = originId;
  if (note) payload.Note = note;

  return payload;
}

function buildPersonPayload_(row, originByName) {
  const name = personName_(row);
  if (!name) return null;

  const payload = {
    TypeId: 2,
    Name: name
  };

  const email = pick_(row, 'E-mail - Pessoa', 'Email - Pessoa', 'E-mail', 'Email');
  const cpf = onlyDigits_(pick_(row, 'CPF - Pessoa', 'CPF'));
  const birthday = normalizeDate_(pick_(row, 'Data de nascimento - Pessoa', 'Data nascimento - Pessoa'));
  const phone = onlyDigits_(pick_(row, 'Telefones - Pessoa', 'Telefone - Pessoa', 'Telefones'));
  const originId = originId_(row, originByName);
  const note = joinedNote_(
    fieldNote_('Cargo', pick_(row, 'Cargo - Pessoa')),
    fieldNote_('Departamento', pick_(row, 'Departamento - Pessoa')),
    fieldNote_('Marcadores', pick_(row, 'Marcadores - Empresa', 'Marcadores')),
    pick_(row, 'Relação', 'Relacao'),
    pick_(row, 'Observações', 'Observacoes')
  );

  if (email) payload.Email = email;
  if (cpf) payload.Register = cpf;
  if (birthday) payload.Birthday = birthday;
  if (originId) payload.OriginId = originId;
  if (note) payload.Note = note;
  if (phone) payload.Phones = [{ PhoneNumber: phone }];

  return payload;
}

function validatePlan_(plan) {
  if (plan.kind === 'empresa_sem_pessoa' && (!plan.company || plan.person)) {
    throw new Error('Plano inválido: empresa_sem_pessoa deve ter somente empresa.');
  }
  if (plan.kind === 'empresa_com_pessoa' && (!plan.company || !plan.person)) {
    throw new Error('Plano inválido: empresa_com_pessoa deve ter empresa e pessoa.');
  }
  if (plan.kind === 'pessoa_fisica_sem_empresa') {
    if (!plan.person || plan.company) throw new Error('Plano inválido: pessoa_fisica_sem_empresa deve ter somente pessoa.');
    validatePersonPayload_(plan.person, plan.kind);
  }
}

function validatePersonPayload_(payload, kind) {
  if (!payload || payload.TypeId !== 2) throw new Error('Payload de pessoa inválido.');
  if (kind === 'pessoa_fisica_sem_empresa') {
    const forbidden = ['CompanyId', 'LegalName', 'CNPJ', 'Company'].filter(key => Object.prototype.hasOwnProperty.call(payload, key));
    if (forbidden.length) {
      throw new Error(`Pessoa física sem empresa recebeu campos proibidos: ${forbidden.join(', ')}`);
    }
  }
}

function createOrUpdateContact_(apiKey, payload, finder) {
  const existing = finder(apiKey, payload);
  if (existing) {
    if (!CONFIG.UPDATE_EXISTING) return { action: 'skipped_existing', id: existing.Id, payload, existing };
    if (CONFIG.COMPARE_BEFORE_UPDATE && !payloadDiffers_(payload, existing)) {
      return { action: 'unchanged', id: existing.Id, payload, existing };
    }
    apiRequest_(apiKey, 'PATCH', `/Contacts(${existing.Id})`, payload);
    return { action: 'updated', id: existing.Id, payload, existing };
  }

  const response = apiRequest_(apiKey, 'POST', '/Contacts', payload);
  const id = extractContactId_(response);
  if (!id) throw new Error(`Ploomes criou contato mas não retornou Id: ${JSON.stringify(response)}`);
  return { action: 'created', id, payload, response };
}

function extractContactId_(response) {
  if (!response) return '';
  if (response.Id) return response.Id;
  if (Array.isArray(response.value) && response.value.length && response.value[0].Id) return response.value[0].Id;
  return '';
}

function payloadDiffers_(payload, existing) {
  const keys = Object.keys(payload).filter(key => key !== 'Phones');
  for (const key of keys) {
    if (normalizeCompareValue_(payload[key]) !== normalizeCompareValue_(existing[key])) return true;
  }
  return false;
}

function normalizeCompareValue_(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return clean(value);
}

function findCompany_(apiKey, payload) {
  if (payload.Register) {
    const found = firstContact_(apiKey, `TypeId eq 1 and Register eq '${odataEscape_(payload.Register)}'`);
    if (found) return found;
  }
  return firstContact_(apiKey, `TypeId eq 1 and Name eq '${odataEscape_(payload.Name)}'`);
}

function findPerson_(apiKey, payload) {
  if (payload.Email) {
    const found = firstContact_(apiKey, `TypeId eq 2 and Email eq '${odataEscape_(payload.Email)}'`);
    if (found) return found;
  }
  if (payload.Register) {
    const found = firstContact_(apiKey, `TypeId eq 2 and Register eq '${odataEscape_(payload.Register)}'`);
    if (found) return found;
  }
  return firstContact_(apiKey, `TypeId eq 2 and Name eq '${odataEscape_(payload.Name)}'`);
}

function firstContact_(apiKey, filterExpr) {
  const data = apiRequest_(apiKey, 'GET', '/Contacts', null, {
    '$filter': filterExpr,
    '$select': 'Id,TypeId,Name,LegalName,Email,Register,CompanyId,OriginId,Note,Website,Birthday,CreateDate',
    '$top': '1'
  });
  const values = data && data.value ? data.value : [];
  return values.length ? values[0] : null;
}


function loadOriginMaps_(apiKey) {
  try {
    const data = apiRequest_(apiKey, 'GET', '/Contacts@Origins', null, {
      '$select': 'Id,Name',
      '$top': '100'
    });
    const origins = data && data.value ? data.value : [];
    const byName = {};
    const byId = {};
    origins.forEach(item => {
      const name = clean(item.Name);
      if (!name) return;
      byName[name.toLowerCase()] = item.Id;
      byId[String(item.Id)] = name;
    });
    return { byName, byId };
  } catch (error) {
    Logger.log(`Não foi possível carregar origens: ${error}`);
    return { byName: {}, byId: {} };
  }
}

function fetchAllContacts_(apiKey, typeId) {
  const items = [];
  let path = `/Contacts?$filter=${encodeURIComponent(`TypeId eq ${typeId}`)}&$select=${encodeURIComponent('Id,TypeId,Name,LegalName,Email,Register,CompanyId,OriginId,Note,Website,Birthday,CreateDate')}&$top=${CONFIG.PULL_PAGE_SIZE}`;
  while (path) {
    const data = apiRequest_(apiKey, 'GET', path.replace(CONFIG.API_BASE, ''), null, null);
    const values = data && data.value ? data.value : [];
    values.forEach(v => items.push(v));
    path = data && data['@odata.nextLink'] ? String(data['@odata.nextLink']) : '';
    if (path.startsWith(CONFIG.API_BASE)) path = path.slice(CONFIG.API_BASE.length);
  }
  return items;
}

function findRowByPloomesIds_(sheet, headerMap, companyId, personId) {
  const lastRow = sheet.getLastRow();
  for (let rowNumber = 2; rowNumber <= lastRow; rowNumber++) {
    const row = rowObject_(sheet.getRange(rowNumber, 1, 1, sheet.getLastColumn()).getValues()[0], headerMap);
    const rowCompanyId = clean(row['Ploomes Id Empresa']);
    const rowPersonId = clean(row['Ploomes Id Pessoa']);
    if (personId && rowPersonId === String(personId)) return rowNumber;
    if (companyId && rowCompanyId === String(companyId) && !rowPersonId) return rowNumber;
  }
  return lastRow + 1;
}
function setCellIfExists_(sheet, rowNumber, headerMap, header, value) {
  const col = headerMap[header];
  if (col === undefined) return;
  sheet.getRange(rowNumber, col + 1).setValue(value === undefined || value === null ? '' : value);
}

function upsertCompanyFromPloomes_(sheet, headerMap, company, originById) {
  const rowNumber = findRowByPloomesIds_(sheet, headerMap, company.Id, '');
  setCellIfExists_(sheet, rowNumber, headerMap, 'Razão Social - Empresa', clean(company.LegalName) || clean(company.Name));
  setCellIfExists_(sheet, rowNumber, headerMap, 'CNPJ - Empresa', clean(company.Register));
  setCellIfExists_(sheet, rowNumber, headerMap, 'Site', clean(company.Website));
  setCellIfExists_(sheet, rowNumber, headerMap, 'Origem - Empresa', originById[String(company.OriginId)] || '');
  setCellIfExists_(sheet, rowNumber, headerMap, 'Observações', clean(company.Note));
  setCellIfExists_(sheet, rowNumber, headerMap, 'Tipo Detectado', 'empresa_sem_pessoa');
  writeStatus_(sheet, rowNumber, headerMap, STATUS.SENT, company.Id, '', '', new Date());
}

function upsertPersonFromPloomes_(sheet, headerMap, person, companyById, originById) {
  const linkedCompany = person.CompanyId ? companyById[String(person.CompanyId)] : null;
  const rowNumber = findRowByPloomesIds_(sheet, headerMap, linkedCompany ? linkedCompany.Id : '', person.Id);
  if (linkedCompany) {
    setCellIfExists_(sheet, rowNumber, headerMap, 'Razão Social - Empresa', clean(linkedCompany.LegalName) || clean(linkedCompany.Name));
    setCellIfExists_(sheet, rowNumber, headerMap, 'CNPJ - Empresa', clean(linkedCompany.Register));
    setCellIfExists_(sheet, rowNumber, headerMap, 'Site', clean(linkedCompany.Website));
    setCellIfExists_(sheet, rowNumber, headerMap, 'Origem - Empresa', originById[String(linkedCompany.OriginId)] || '');
    setCellIfExists_(sheet, rowNumber, headerMap, 'Ploomes Id Empresa', String(linkedCompany.Id));
  }
  setCellIfExists_(sheet, rowNumber, headerMap, 'Nome - Pessoa', clean(person.Name));
  setCellIfExists_(sheet, rowNumber, headerMap, 'E-mail - Pessoa', clean(person.Email));
  setCellIfExists_(sheet, rowNumber, headerMap, 'CPF - Pessoa', clean(person.Register));
  setCellIfExists_(sheet, rowNumber, headerMap, 'Data de nascimento - Pessoa', clean(person.Birthday));
  setCellIfExists_(sheet, rowNumber, headerMap, 'Origem - Pessoa', originById[String(person.OriginId)] || '');
  setCellIfExists_(sheet, rowNumber, headerMap, 'Observações', clean(person.Note));
  setCellIfExists_(sheet, rowNumber, headerMap, 'Tipo Detectado', linkedCompany ? 'empresa_com_pessoa' : 'pessoa_fisica_sem_empresa');
  writeStatus_(sheet, rowNumber, headerMap, STATUS.SENT, linkedCompany ? linkedCompany.Id : '', person.Id, '', new Date());
}

function importarDoPloomes() {
  return importarDoPloomesLote_(null, null);
}

function importarDoPloomesLote(maxCompanies, maxPeople) {
  return importarDoPloomesLote_(maxCompanies, maxPeople);
}

function importarDoPloomesLote_(maxCompanies, maxPeople) {
  const apiKey = getApiKey_();
  const sheet = getSheet_();
  const headerMap = ensureControlColumns_(sheet);
  const originMaps = loadOriginMaps_(apiKey);
  const companies = fetchAllContacts_(apiKey, 1);
  const people = fetchAllContacts_(apiKey, 2);
  const companyById = {};
  const companiesToImport =
    maxCompanies === null || maxCompanies === undefined || maxCompanies === ''
      ? companies
      : companies.slice(0, Number(maxCompanies));
  const peopleToImport =
    maxPeople === null || maxPeople === undefined || maxPeople === ''
      ? people
      : people.slice(0, Number(maxPeople));

  Logger.log(`Iniciando importação do Ploomes. Empresas: ${companiesToImport.length}/${companies.length}. Pessoas: ${peopleToImport.length}/${people.length}.`);

  companiesToImport.forEach((company, index) => {
    companyById[String(company.Id)] = company;
    upsertCompanyFromPloomes_(sheet, headerMap, company, originMaps.byId);
    if ((index + 1) % 10 === 0 || index === companiesToImport.length - 1) {
      Logger.log(`Empresas importadas: ${index + 1}/${companiesToImport.length}`);
    }
  });

  peopleToImport.forEach((person, index) => {
    upsertPersonFromPloomes_(sheet, headerMap, person, companyById, originMaps.byId);
    if ((index + 1) % 10 === 0 || index === peopleToImport.length - 1) {
      Logger.log(`Pessoas importadas: ${index + 1}/${peopleToImport.length}`);
    }
  });

  SpreadsheetApp.flush();
  return notify_(`Importação concluída.\nEmpresas: ${companiesToImport.length}\nPessoas: ${peopleToImport.length}`);
}
function loadOrigins_(apiKey) {
  return loadOriginMaps_(apiKey).byName;
}

function originId_(row, originByName) {
  const origin = pick_(row, 'Origem - Empresa', 'Origem - Pessoa', 'Origem');
  if (!origin) return null;
  return originByName[origin.toLowerCase()] || null;
}

function apiRequest_(apiKey, method, path, payload, params) {
  let url = CONFIG.API_BASE + path;
  if (params) url += '?' + buildQuery_(params);

  const options = {
    method,
    muteHttpExceptions: true,
    headers: {
      'User-Key': apiKey,
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      'User-Agent': 'Mozilla/5.0'
    }
  };

  if (payload) options.payload = JSON.stringify(payload);

  const response = UrlFetchApp.fetch(url, options);
  const code = response.getResponseCode();
  const text = response.getContentText() || '';

  if (code >= 200 && code < 300) {
    return text ? JSON.parse(text) : {};
  }

  throw new Error(`${method} ${url} -> HTTP ${code}: ${text.slice(0, 800)}`);
}

function buildQuery_(params) {
  return Object.keys(params)
    .map(key => `${encodeURIComponent(key)}=${encodeURIComponent(params[key])}`)
    .join('&');
}

function getApiKey_() {
  const key = PropertiesService.getScriptProperties().getProperty('PLOOMES_API_KEY');
  if (!key) throw new Error('Configure PLOOMES_API_KEY em Script Properties usando o menu Ploomes > Configurar API key.');
  return key;
}

function getSheet_() {
  const spreadsheetId = PropertiesService.getScriptProperties().getProperty('PLOOMES_SPREADSHEET_ID') || CONFIG.SPREADSHEET_ID;
  const spreadsheet = spreadsheetId ? SpreadsheetApp.openById(spreadsheetId) : SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(CONFIG.SHEET_NAME);
  if (!sheet) throw new Error(`Aba não encontrada: ${CONFIG.SHEET_NAME}`);
  return sheet;
}

function ensureControlColumns_(sheet) {
  const values = sheet.getDataRange().getValues();
  if (!values.length) throw new Error('Planilha vazia.');

  const headers = values[0].map(clean);
  CONFIG.CONTROL_COLUMNS.forEach(name => {
    if (!headers.includes(name)) {
      headers.push(name);
      sheet.getRange(1, headers.length).setValue(name);
    }
  });

  const refreshed = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(clean);
  const map = {};
  refreshed.forEach((header, index) => {
    if (header) map[header] = index;
  });

  return map;
}

function rowObject_(values, headerMap) {
  const row = {};
  Object.keys(headerMap).forEach(header => {
    row[header] = values[headerMap[header]];
  });
  return row;
}

function rowKind_(row) {
  const hasCompany = Boolean(companyName_(row));
  const hasPerson = Boolean(personName_(row));
  if (hasCompany && hasPerson) return 'empresa_com_pessoa';
  if (hasCompany) return 'empresa_sem_pessoa';
  if (hasPerson) return 'pessoa_fisica_sem_empresa';
  return 'ignorar';
}

function companyName_(row) {
  return pick_(
    row,
    'Razão Social - Empresa',
    'Razao Social - Empresa',
    'Razão social - Empresa',
    'Razao social - Empresa',
    'Nome - Empresa',
    'Nome Empresa'
  );
}

function personName_(row) {
  return pick_(row, 'Nome - Pessoa', 'Nome Pessoa');
}

function pick_(row, ...names) {
  for (const name of names) {
    if (Object.prototype.hasOwnProperty.call(row, name)) {
      const value = clean(row[name]);
      if (value) return value;
    }
  }
  return '';
}

function writeStatus_(sheet, rowNumber, headerMap, status, companyId, personId, error, date) {
  setCell_(sheet, rowNumber, headerMap, 'Status Importação', status);
  if (companyId !== '') setCell_(sheet, rowNumber, headerMap, 'Ploomes Id Empresa', companyId);
  if (personId !== '') setCell_(sheet, rowNumber, headerMap, 'Ploomes Id Pessoa', personId);
  setCell_(sheet, rowNumber, headerMap, 'Erro Importação', error || '');
  setCell_(sheet, rowNumber, headerMap, 'Última sincronização', date || new Date());
}

function setCell_(sheet, rowNumber, headerMap, header, value) {
  const col = headerMap[header];
  if (col === undefined) throw new Error(`Coluna de controle ausente: ${header}`);
  sheet.getRange(rowNumber, col + 1).setValue(value);
}

function clean(value) {
  if (value === null || value === undefined) return '';
  if (value instanceof Date) return value;
  const text = String(value).trim();
  if (!text) return '';
  if (['nan', 'none', 'null'].includes(text.toLowerCase())) return '';
  if (/^\d+\.0$/.test(text)) return text.slice(0, -2);
  return text;
}

function onlyDigits_(value) {
  return clean(value).replace(/\D/g, '');
}

function normalizeDate_(value) {
  if (!value) return '';
  if (value instanceof Date) {
    return Utilities.formatDate(value, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  }
  const text = clean(value);
  if (!text) return '';
  const br = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/);
  if (br) {
    const day = br[1].padStart(2, '0');
    const month = br[2].padStart(2, '0');
    const year = br[3].length === 2 ? `20${br[3]}` : br[3];
    return `${year}-${month}-${day}`;
  }
  return text;
}

function joinedNote_(...parts) {
  return parts.map(clean).filter(Boolean).join('\n');
}

function fieldNote_(label, value) {
  const cleaned = clean(value);
  return cleaned ? `${label}: ${cleaned}` : '';
}

function odataEscape_(value) {
  return clean(value).replace(/'/g, "''");
}
