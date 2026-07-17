function workflow_bridge(request_path, result_path)
started = tic;
result = struct('protocol_version','1.0','status','failed','action','unknown', ...
    'matlab_version',version,'release',version('-release'),'architecture',computer, ...
    'duration_seconds',0,'outputs',{{}},'artifacts',{{}},'error',[]);
try
    request = jsondecode(fileread(request_path));
    validate_request(request);
    result.action = request.action;
    root = canonical_path(request.project_root);
    attempt_dir = canonical_path(request.attempt_dir);
    assert(starts_with_path(attempt_dir, root), 'workflow:UnsafePath', ...
        'Attempt directory is outside the project root.');
    if ~isfolder(attempt_dir), mkdir(attempt_dir); end
    original = pwd;
    restore_dir = onCleanup(@() cd(original));
    cd(root);
    [outputs, artifacts, details] = execute_action(request.action, request.parameters, root, attempt_dir);
    result.outputs = normalize_outputs(outputs, attempt_dir);
    result.artifacts = artifacts;
    result.details = details;
    result.status = 'succeeded';
catch exception
    result.status = 'failed';
    result.error = struct('identifier',exception.identifier,'message',exception.message, ...
        'stack',{arrayfun(@(item) struct('name',item.name,'line',item.line,'file',item.file), ...
        exception.stack,'UniformOutput',false)});
end
result.duration_seconds = toc(started);
write_json_atomic(result_path, result);
if strcmp(result.status,'failed')
    error(result.error.identifier, '%s', result.error.message);
end
end

function validate_request(request)
required = {'protocol_version','action','parameters','project_root','attempt_dir'};
for index = 1:numel(required)
    assert(isfield(request,required{index}), 'workflow:InvalidRequest', ...
        'Missing request field: %s', required{index});
end
assert(strcmp(request.protocol_version,'1.0'), 'workflow:ProtocolMismatch', ...
    'Unsupported protocol version: %s', request.protocol_version);
end

function [outputs, artifacts, details] = execute_action(action, params, root, attempt_dir)
outputs = {}; artifacts = {}; details = struct();
add_paths = parameter_or(params,'add_paths',{});
if ischar(add_paths) || isstring(add_paths), add_paths = {add_paths}; end
for path_index = 1:numel(add_paths)
    addpath(secure_path(root,add_paths{path_index},true));
end
switch action
    case 'call_function'
        validate_function_name(params.function);
        args = decode_arguments(params);
        count = double(parameter_or(params,'nargout',1));
        outputs = cell(1,count);
        [outputs{:}] = feval(params.function,args{:});
    case 'run_script'
        script = secure_path(root,params.script,true);
        run_script_isolated(script);
        details.script = relative_path(script,root);
    case 'run_tests'
        test_path = secure_path(root,params.path,true);
        test_result = runtests(test_path);
        details.test_count = numel(test_result);
        details.passed = sum([test_result.Passed]);
        details.failed = sum([test_result.Failed]);
        details.incomplete = sum([test_result.Incomplete]);
        assert(all([test_result.Passed]), 'workflow:MatlabTestsFailed', ...
            'MATLAB tests failed or were incomplete.');
    case 'check_code'
        code_path = secure_path(root,params.path,true);
        outputs = {checkcode(code_path,'-id')};
    case 'run_simulink'
        model = secure_path(root,params.model,true);
        [~,model_name] = fileparts(model);
        load_system(model);
        close_model = onCleanup(@() close_system(model_name,0));
        simulation_input = Simulink.SimulationInput(model_name);
        variables = parameter_or(params,'variables',struct());
        names = fieldnames(variables);
        for index = 1:numel(names)
            simulation_input = simulation_input.setVariable(names{index},variables.(names{index}));
        end
        model_parameters = parameter_or(params,'model_parameters',struct());
        names = fieldnames(model_parameters);
        for index = 1:numel(names)
            simulation_input = simulation_input.setModelParameter(names{index},string(model_parameters.(names{index})));
        end
        simulation_output = sim(simulation_input);
        mat_path = fullfile(attempt_dir,'simulink_output.mat');
        save(mat_path,'simulation_output','-v7.3');
        artifacts = {artifact_record(mat_path,root)};
        details.model = relative_path(model,root);
    case 'create_simulink_model'
        [artifacts, details] = create_basic_simulink_model(params,root,attempt_dir);
        outputs = {details};
    case 'configure_simulink_model'
        [artifacts, details] = configure_advanced_simulink_model(params,root,attempt_dir);
        outputs = {details};
    case 'eval_expression'
        assert(logical(params.allow_eval), 'workflow:PolicyBlocked', ...
            'Expression evaluation requires allow_eval=true.');
        outputs = {eval(params.expression)};
    case 'workflow'
        operations = params.operations;
        operation_results = cell(1,numel(operations));
        for index = 1:numel(operations)
            operation = operations(index);
            [operation_outputs, operation_artifacts, operation_details] = ...
                execute_action(operation.action,operation.parameters,root,attempt_dir);
            operation_results{index} = struct('action',operation.action, ...
                'outputs',{normalize_outputs(operation_outputs,attempt_dir)}, ...
                'artifacts',{operation_artifacts},'details',operation_details);
            artifacts = [artifacts operation_artifacts]; %#ok<AGROW>
        end
        outputs = operation_results;
    case 'toolbox_info'
        products = ver;
        details.products = arrayfun(@(item) struct('name',item.Name,'version',item.Version, ...
            'release',item.Release,'date',item.Date),products);
        details.license_inuse = license('inuse');
    case 'compiler_status'
        details = compiler_status_details();
    case 'build_mex'
        sources = parameter_or(params,'sources',{});
        if ischar(sources) || isstring(sources), sources = cellstr(sources); end
        assert(iscell(sources) && ~isempty(sources), 'workflow:InvalidRequest', ...
            'build_mex requires one or more source files.');
        output_dir = secure_path(root,parameter_or(params,'output_dir','build/mex'),false);
        if ~isfolder(output_dir), mkdir(output_dir); end
        mex_args = {'-v','-outdir',output_dir};
        output_name = char(parameter_or(params,'output_name',''));
        if ~isempty(output_name)
            assert(~isempty(regexp(output_name,'^[A-Za-z]\w*$','once')), ...
                'workflow:InvalidRequest','Invalid MEX output name.');
            mex_args = [mex_args {'-output',output_name}]; %#ok<AGROW>
        end
        extra_args = parameter_or(params,'mex_arguments',{});
        if ischar(extra_args) || isstring(extra_args), extra_args = cellstr(extra_args); end
        mex_args = [mex_args extra_args]; %#ok<AGROW>
        source_paths = cell(1,numel(sources));
        for source_index = 1:numel(sources)
            source_paths{source_index} = secure_path(root,sources{source_index},true);
        end
        mex(mex_args{:},source_paths{:});
        if isempty(output_name), [~,output_name] = fileparts(source_paths{1}); end
        mex_path = fullfile(output_dir,[output_name '.' mexext]);
        assert(isfile(mex_path),'workflow:MissingArtifact','MEX output was not generated.');
        artifacts = {artifact_record(mex_path,root)};
        details.output = relative_path(mex_path,root);
        details.compiler = compiler_config_struct(mex.getCompilerConfigurations( ...
            char(parameter_or(params,'language','C')),'Selected'));
    case 'run_rapid_accelerator'
        model = secure_path(root,params.model,true);
        [model_dir,model_name] = fileparts(model);
        configure_matlab_build_environment();
        [staging_root,~,~,filegen_cleanup] = configure_ascii_file_generation(); %#ok<ASGLU>
        addpath(model_dir);
        model_path_cleanup = onCleanup(@() rmpath(model_dir));
        rapid_original_dir = pwd;
        cd(staging_root);
        rapid_dir_cleanup = onCleanup(@() cd(rapid_original_dir));
        load_system(model);
        close_model = onCleanup(@() close_system(model_name,0));
        simulation_input = Simulink.SimulationInput(model_name);
        variables = parameter_or(params,'variables',struct());
        names = fieldnames(variables);
        for index = 1:numel(names)
            simulation_input = simulation_input.setVariable(names{index},variables.(names{index}));
        end
        model_parameters = parameter_or(params,'model_parameters',struct());
        names = fieldnames(model_parameters);
        for index = 1:numel(names)
            simulation_input = simulation_input.setModelParameter(names{index},string(model_parameters.(names{index})));
        end
        simulation_input = simulation_input.setModelParameter('SimulationMode','rapid');
        simulation_output = sim(simulation_input);
        mat_path = fullfile(attempt_dir,'rapid_accelerator_output.mat');
        save(mat_path,'simulation_output','-v7.3');
        artifacts = {artifact_record(mat_path,root)};
        details.model = relative_path(model,root);
        details.simulation_mode = 'rapid';
        details.ascii_build_staging = staging_root;
        details.compiler = compiler_status_details();
    case 'matlab_codegen'
        entry_path = secure_path(root,params.entry_point,true);
        [entry_dir,function_name,entry_extension] = fileparts(entry_path);
        configure_matlab_build_environment();
        output_dir = secure_path(root,parameter_or(params,'output_dir','build/matlab_coder'),false);
        if ~isfolder(output_dir), mkdir(output_dir); end
        staging_root = create_ascii_staging_root();
        staging_cleanup = onCleanup(@() remove_staging_root(staging_root));
        staging_source = fullfile(staging_root,'source');
        staging_output = fullfile(staging_root,'output');
        mkdir(staging_source); mkdir(staging_output);
        source_files = dir(fullfile(entry_dir,'*.m'));
        for source_index = 1:numel(source_files)
            copyfile(fullfile(source_files(source_index).folder,source_files(source_index).name), ...
                fullfile(staging_source,source_files(source_index).name),'f');
        end
        staging_entry = fullfile(staging_source,[function_name entry_extension]);
        assert(isfile(staging_entry),'workflow:MissingPath','Failed to stage MATLAB Coder entry point.');
        addpath(staging_source);
        path_cleanup = onCleanup(@() rmpath(staging_source));
        arguments = decode_arguments(params);
        configuration = char(parameter_or(params,'configuration','mex'));
        assert(any(strcmp(configuration,{'mex','lib','dll','exe'})), ...
            'workflow:InvalidRequest','Unsupported MATLAB Coder configuration.');
        original_codegen_dir = pwd;
        codegen_dir_cleanup = onCleanup(@() cd(original_codegen_dir));
        cd(staging_source);
        codegen(['-config:' configuration],'-d',staging_output,function_name,'-args',arguments);
        copyfile(fullfile(staging_output,'*'),output_dir,'f');
        generated = dir(fullfile(output_dir,'**','*'));
        generated = generated(~[generated.isdir]);
        assert(~isempty(generated),'workflow:MissingArtifact','MATLAB Coder produced no files.');
        for index = 1:numel(generated)
            artifacts{end+1} = artifact_record(fullfile(generated(index).folder,generated(index).name),root); %#ok<AGROW>
        end
        details.entry_point = relative_path(entry_path,root);
        details.configuration = configuration;
        details.output_dir = relative_path(output_dir,root);
        details.ascii_build_staging = true;
    case 'simulink_codegen'
        model = secure_path(root,params.model,true);
        [~,model_name] = fileparts(model);
        configure_matlab_build_environment();
        [staging_root,~,staging_codegen,filegen_cleanup] = configure_ascii_file_generation(); %#ok<ASGLU>
        load_system(model);
        close_model = onCleanup(@() close_system(model_name,0));
        system_target_file = char(parameter_or(params,'system_target_file','grt.tlc'));
        set_param(model_name,'SystemTargetFile',system_target_file);
        set_param(model_name,'GenCodeOnly',char(parameter_or(params,'generate_code_only','off')));
        slbuild(model_name);
        output_dir = secure_path(root,parameter_or(params,'output_dir','build/simulink_coder'),false);
        if ~isfolder(output_dir), mkdir(output_dir); end
        copyfile(fullfile(staging_codegen,'*'),output_dir,'f');
        details.model = relative_path(model,root);
        details.system_target_file = system_target_file;
        details.generate_code_only = get_param(model_name,'GenCodeOnly');
        details.output_dir = relative_path(output_dir,root);
        details.ascii_build_staging = staging_root;
        generated_candidates = {output_dir};
        for candidate_index = 1:numel(generated_candidates)
            candidate = generated_candidates{candidate_index};
            if isfolder(candidate)
                files = dir(fullfile(candidate,'**','*'));
                files = files(~[files.isdir]);
                for index = 1:numel(files)
                    artifacts{end+1} = artifact_record(fullfile(files(index).folder,files(index).name),root); %#ok<AGROW>
                end
            end
        end
    case {'identify_model','design_controller','design_observer','robustness_sweep','export_results'}
        assert(isfield(params,'function'), 'workflow:InvalidRequest', ...
            '%s requires a project wrapper function.', action);
        validate_function_name(params.function);
        args = decode_arguments(params);
        outputs = {feval(params.function,args{:})};
    otherwise
        error('workflow:UnsupportedAction','Unsupported bridge action: %s',action);
end
artifacts = [artifacts export_figures(params,root,attempt_dir)];
end

function [artifacts, details] = create_basic_simulink_model(params,root,attempt_dir)
model_path = secure_path(root,params.model,false);
[model_dir,model_name,extension] = fileparts(model_path);
assert(~isempty(regexp(model_name,'^[A-Za-z]\w*$','once')), ...
    'workflow:InvalidRequest','Invalid Simulink model name.');
if isempty(extension)
    model_path = [model_path '.slx'];
elseif ~strcmpi(extension,'.slx')
    error('workflow:InvalidRequest','Simulink model must use the .slx extension.');
end
if ~isfolder(model_dir), mkdir(model_dir); end
overwrite = logical(parameter_or(params,'overwrite',false));
assert(overwrite || ~isfile(model_path),'workflow:ArtifactExists', ...
    'Model already exists and overwrite=false: %s',relative_path(model_path,root));
if bdIsLoaded(model_name), close_system(model_name,0); end
new_system(model_name);
close_model = onCleanup(@() close_system(model_name,0));
blocks = params.blocks;
allowed = {'simulink/Continuous/Integrator','simulink/Continuous/State-Space', ...
    'simulink/Continuous/Transfer Fcn','simulink/Discrete/Unit Delay', ...
    'simulink/Math Operations/Gain','simulink/Math Operations/Sum', ...
    'simulink/Ports & Subsystems/In1','simulink/Ports & Subsystems/Out1', ...
    'simulink/Signal Routing/Demux','simulink/Signal Routing/Mux', ...
    'simulink/Sinks/Display','simulink/Sinks/Scope','simulink/Sinks/To Workspace', ...
    'simulink/Sources/Constant','simulink/Sources/Sine Wave','simulink/Sources/Step', ...
    'simulink/Discontinuities/Saturation'};
for index = 1:numel(blocks)
    library = char(blocks(index).library);
    assert(any(strcmp(library,allowed)),'workflow:PolicyBlocked', ...
        'Block library is not in the safe basic registry: %s',library);
    block_name = char(blocks(index).name);
    assert(~isempty(regexp(block_name,'^[A-Za-z]\w*$','once')), ...
        'workflow:InvalidRequest','Invalid block name: %s',block_name);
    block_path = [model_name '/' block_name];
    add_block(library,block_path);
    if isfield(blocks(index),'position') && ~isempty(blocks(index).position)
        set_param(block_path,'Position',double(blocks(index).position));
    end
    if isfield(blocks(index),'parameters')
        apply_simulink_parameters(block_path,blocks(index).parameters);
    end
end
connections = parameter_or(params,'connections',struct([]));
for index = 1:numel(connections)
    add_line(model_name,char(connections(index).src),char(connections(index).dst),'autorouting','on');
end
model_parameters = parameter_or(params,'model_parameters',struct());
apply_simulink_parameters(model_name,model_parameters);
save_system(model_name,model_path);
artifacts = {artifact_record(model_path,root)};
simulated = logical(parameter_or(params,'simulate',false));
if simulated
    simulation_input = Simulink.SimulationInput(model_name);
    variables = parameter_or(params,'variables',struct());
    names = fieldnames(variables);
    for index = 1:numel(names)
        simulation_input = simulation_input.setVariable(names{index},variables.(names{index}));
    end
    simulation_output = sim(simulation_input);
    mat_path = fullfile(attempt_dir,'structured_simulink_output.mat');
    save(mat_path,'simulation_output','-v7.3');
    artifacts{end+1} = artifact_record(mat_path,root);
end
details = struct('model',relative_path(model_path,root),'block_count',numel(blocks), ...
    'connection_count',numel(connections),'simulated',simulated, ...
    'solver',get_param(model_name,'Solver'),'solver_type',get_param(model_name,'SolverType'), ...
    'stop_time',get_param(model_name,'StopTime'));
end

function apply_simulink_parameters(target,parameters)
if isempty(parameters), return; end
names = fieldnames(parameters);
for index = 1:numel(names)
    value = parameters.(names{index});
    if isstring(value) || ischar(value)
        value = char(value);
    elseif isnumeric(value) || islogical(value)
        if isscalar(value), value = num2str(value); else, value = mat2str(value); end
    else
        error('workflow:InvalidRequest','Unsupported Simulink parameter value: %s',names{index});
    end
    set_param(target,names{index},value);
end
end

function [artifacts, details] = configure_advanced_simulink_model(params,root,attempt_dir)
model_path = secure_path(root,params.model,true);
[model_dir,model_name] = fileparts(model_path);
addpath(model_dir);
model_path_cleanup = onCleanup(@() rmpath(model_dir));
load_system(model_path);
close_model = onCleanup(@() close_system(model_name,0));
artifacts = {};
dictionary = [];
dictionary_cleanup = [];
dictionary_path = '';
if isfield(params,'data_dictionary') && ~isempty(params.data_dictionary)
    dictionary_path = secure_path(root,params.data_dictionary.path,false);
    [dictionary_dir,dictionary_name,dictionary_extension] = fileparts(dictionary_path);
    assert(strcmpi(dictionary_extension,'.sldd'),'workflow:InvalidRequest', ...
        'Data dictionary must use .sldd extension.');
    if ~isfolder(dictionary_dir), mkdir(dictionary_dir); end
    addpath(dictionary_dir);
    dictionary_path_cleanup = onCleanup(@() rmpath(dictionary_dir)); %#ok<NASGU>
    if isfile(dictionary_path)
        dictionary = Simulink.data.dictionary.open(dictionary_path);
    else
        dictionary = Simulink.data.dictionary.create(dictionary_path);
    end
    dictionary_cleanup = onCleanup(@() close(dictionary));
    design_data = getSection(dictionary,'Design Data');
    entries = parameter_or(params.data_dictionary,'entries',struct());
    names = fieldnames(entries);
    for index = 1:numel(names)
        set_dictionary_entry(design_data,names{index},entries.(names{index}));
    end
    set_param(model_name,'DataDictionary',[dictionary_name dictionary_extension]);
end
buses = parameter_or(params,'buses',struct([]));
for bus_index = 1:numel(buses)
    bus = Simulink.Bus;
    raw_elements = buses(bus_index).elements;
    elements = repmat(Simulink.BusElement,1,numel(raw_elements));
    for element_index = 1:numel(raw_elements)
        elements(element_index).Name = char(raw_elements(element_index).name);
        elements(element_index).DataType = char(raw_elements(element_index).data_type);
        elements(element_index).Dimensions = double(raw_elements(element_index).dimensions);
    end
    bus.Elements = elements;
    bus_name = char(buses(bus_index).name);
    if isempty(dictionary)
        assignin('base',bus_name,bus);
    else
        set_dictionary_entry(design_data,bus_name,bus);
    end
end
variants = parameter_or(params,'variant_controls',struct([]));
for index = 1:numel(variants)
    variant = Simulink.VariantExpression(char(variants(index).condition));
    variant_name = char(variants(index).name);
    if isempty(dictionary)
        assignin('base',variant_name,variant);
    else
        set_dictionary_entry(design_data,variant_name,variant);
    end
end
references = parameter_or(params,'model_references',struct([]));
for index = 1:numel(references)
    reference_path = secure_path(root,references(index).model,true);
    [reference_dir,reference_name,reference_extension] = fileparts(reference_path);
    assert(strcmpi(reference_extension,'.slx'),'workflow:InvalidRequest', ...
        'Referenced model must use .slx extension.');
    addpath(reference_dir);
    reference_path_cleanup = onCleanup(@() rmpath(reference_dir)); %#ok<NASGU>
    block_name = char(references(index).name);
    block_path = [model_name '/' block_name];
    if getSimulinkBlockHandle(block_path) == -1
        add_block('simulink/Ports & Subsystems/Model',block_path);
    end
    set_param(block_path,'ModelName',reference_name);
    if isfield(references(index),'position') && ~isempty(references(index).position)
        set_param(block_path,'Position',double(references(index).position));
    end
    if isfield(references(index),'parameters')
        apply_simulink_parameters(block_path,references(index).parameters);
    end
end
sample_times = parameter_or(params,'sample_times',struct([]));
for index = 1:numel(sample_times)
    block_path = [model_name '/' char(sample_times(index).block)];
    assert(getSimulinkBlockHandle(block_path) ~= -1,'workflow:MissingPath', ...
        'Sample-time block does not exist: %s',block_path);
    value = sample_times(index).sample_time;
    if isnumeric(value), value = num2str(value); else, value = char(value); end
    set_param(block_path,'SampleTime',value);
end
connections = parameter_or(params,'connections',struct([]));
for index = 1:numel(connections)
    add_line(model_name,char(connections(index).src),char(connections(index).dst),'autorouting','on');
end
save_system(model_name,model_path);
artifacts{end+1} = artifact_record(model_path,root);
if ~isempty(dictionary)
    saveChanges(dictionary);
    artifacts{end+1} = artifact_record(dictionary_path,root);
end
simulated = logical(parameter_or(params,'simulate',false));
if simulated
    simulation_output = sim(model_name);
    mat_path = fullfile(attempt_dir,'advanced_simulink_output.mat');
    save(mat_path,'simulation_output','-v7.3');
    artifacts{end+1} = artifact_record(mat_path,root);
end
details = struct('model',relative_path(model_path,root), ...
    'bus_count',numel(buses),'model_reference_count',numel(references), ...
    'variant_control_count',numel(variants),'sample_time_count',numel(sample_times), ...
    'connection_count',numel(connections),'data_dictionary',relative_optional(dictionary_path,root), ...
    'simulated',simulated,'stateflow_available',~isempty(ver('stateflow')), ...
    'simulink_coder_available',~isempty(ver('simulinkcoder')), ...
    'simulink_coder_licensed',logical(license('test','Real-Time_Workshop')));
clear dictionary_cleanup;
end

function set_dictionary_entry(section,name,value)
if exist(section,name)
    entry = getEntry(section,name);
    setValue(entry,value);
else
    addEntry(section,name,value);
end
end

function value = relative_optional(path,root)
if isempty(path), value = ''; else, value = relative_path(path,root); end
end

function details = compiler_status_details()
details = struct;
details.environment = getenv('MW_MINGW64_LOC');
details.c = compiler_config_struct(mex.getCompilerConfigurations('C','Selected'));
details.cpp = compiler_config_struct(mex.getCompilerConfigurations('C++','Selected'));
details.matlab_coder = struct('installed',~isempty(ver('matlabcoder')), ...
    'licensed',logical(license('test','MATLAB_Coder')));
details.simulink_coder = struct('installed',~isempty(ver('simulinkcoder')), ...
    'licensed',logical(license('test','Real-Time_Workshop')));
details.ready = ~isempty(details.c) && ~isempty(details.cpp);
end

function value = compiler_config_struct(configuration)
if isempty(configuration), value = []; return; end
value = struct('name',configuration.Name,'manufacturer',configuration.Manufacturer, ...
    'version',configuration.Version,'location',configuration.Location, ...
    'language',configuration.Language);
end

function root = create_ascii_staging_root()
root = fullfile(tempdir,['matlab_agent_build_' char(java.util.UUID.randomUUID)]);
mkdir(root);
end

function configure_matlab_build_environment()
compatible_root = getenv('MATLAB_AGENT_MATLAB_ROOT');
if isempty(compatible_root) || ~isfolder(compatible_root)
    compatible_root = matlabroot;
end
setenv('MATLAB_ROOT',compatible_root);
setenv('ALT_MATLAB_ROOT',compatible_root);
setenv('MATLAB_BIN',fullfile(compatible_root,'bin'));
setenv('ALT_MATLAB_BIN',fullfile(compatible_root,'bin'));
end

function [root,cache_folder,codegen_folder,cleanup] = configure_ascii_file_generation()
root = create_ascii_staging_root();
cache_folder = fullfile(root,'cache');
codegen_folder = fullfile(root,'codegen');
previous = Simulink.fileGenControl('getConfig');
Simulink.fileGenControl('set','CacheFolder',cache_folder, ...
    'CodeGenFolder',codegen_folder,'createDir',true);
cleanup = onCleanup(@() restore_file_generation(previous,root));
end

function restore_file_generation(previous,root)
try
    Simulink.fileGenControl('setConfig','config',previous);
catch
    Simulink.fileGenControl('reset');
end
remove_staging_root(root);
end

function remove_staging_root(root)
if isfolder(root)
    try, rmdir(root,'s'); catch, end
end
end

function run_script_isolated(script_path)
run(script_path);
end

function outputs = normalize_outputs(values,attempt_dir)
outputs = cell(size(values));
for index = 1:numel(values)
    value = values{index};
    try
        jsonencode(value);
        outputs{index} = value;
    catch
        variable_name = sprintf('output_%d',index);
        mat_path = fullfile(attempt_dir,[variable_name '.mat']);
        payload = value; save(mat_path,'payload','-v7.3');
        outputs{index} = struct('storage','mat','path',mat_path,'class',class(value), ...
            'size',size(value));
    end
end
end

function artifacts = export_figures(params,root,attempt_dir)
artifacts = {};
if ~logical(parameter_or(params,'export_figures',false)), return; end
figures = findall(groot,'Type','figure');
for index = 1:numel(figures)
    png_path = fullfile(attempt_dir,sprintf('figure_%02d.png',index));
    fig_path = fullfile(attempt_dir,sprintf('figure_%02d.fig',index));
    exportgraphics(figures(index),png_path,'Resolution',180);
    savefig(figures(index),fig_path);
    artifacts = [artifacts {artifact_record(png_path,root),artifact_record(fig_path,root)}]; %#ok<AGROW>
end
close(figures);
end

function path = secure_path(root,value,must_exist)
assert(ischar(value) || isstring(value),'workflow:InvalidPath','Path must be text.');
candidate = char(value);
file_object = java.io.File(candidate);
if file_object.isAbsolute(), path = canonical_path(candidate);
else, path = canonical_path(fullfile(root,candidate)); end
assert(starts_with_path(path,root),'workflow:UnsafePath','Path escapes project root: %s',candidate);
if must_exist, assert(isfile(path) || isfolder(path),'workflow:MissingPath','Path not found: %s',candidate); end
end

function path = canonical_path(value)
path = char(java.io.File(char(value)).getCanonicalPath());
end

function result = starts_with_path(path,root)
path = lower(strrep(path,'/','\')); root = lower(strrep(root,'/','\'));
result = strcmp(path,root) || startsWith(path,[root '\']);
end

function value = parameter_or(params,name,default)
if isfield(params,name), value = params.(name); else, value = default; end
end

function args = decode_arguments(params)
if isfield(params,'arguments')
    encoded = params.arguments;
    if isempty(encoded), args = {}; return; end
    if isstruct(encoded)
        args = cell(1,numel(encoded));
        for index = 1:numel(encoded)
            assert(isfield(encoded(index),'value'),'workflow:InvalidArguments', ...
                'Each argument requires a value field.');
            args{index} = encoded(index).value;
        end
    else
        error('workflow:InvalidArguments','arguments must be an array of objects.');
    end
    return
end
legacy = parameter_or(params,'args',{});
mode = char(parameter_or(params,'args_mode','positional'));
if iscell(legacy), args = legacy;
elseif strcmp(mode,'single'), args = {legacy};
elseif isnumeric(legacy) || islogical(legacy), args = num2cell(legacy);
elseif isempty(legacy), args = {};
else, args = {legacy}; end
end

function validate_function_name(name)
assert(~isempty(regexp(char(name),'^[A-Za-z]\w*(\.[A-Za-z]\w*)*$','once')), ...
    'workflow:InvalidFunction','Invalid function name.');
end

function record = artifact_record(path,root)
record = struct('path',relative_path(path,root),'bytes',dir(path).bytes);
end

function value = relative_path(path,root)
path = canonical_path(path); root = canonical_path(root);
value = strrep(path(numel(root)+2:end),'\','/');
end

function write_json_atomic(path,payload)
folder = fileparts(path); if ~isfolder(folder), mkdir(folder); end
temporary = [path '.tmp'];
fid = fopen(temporary,'w','n','UTF-8');
assert(fid ~= -1,'workflow:ResultWriteFailed','Cannot write result file.');
cleanup = onCleanup(@() fclose(fid));
fprintf(fid,'%s',jsonencode(payload,'PrettyPrint',true));
clear cleanup;
movefile(temporary,path,'f');
end
