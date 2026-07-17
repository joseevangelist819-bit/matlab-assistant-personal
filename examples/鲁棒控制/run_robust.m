root=fileparts(mfilename('fullpath'));s=tf('s');a=ureal('a',1,'Percentage',20);plant=1/(s+a);samples=usample(plant,20);stable=true;dc=zeros(1,20);
for i=1:20,stable=stable&&isstable(samples(:,:,i));dc(i)=dcgain(samples(:,:,i));end
result=struct('samples',20,'all_stable',stable,'dc_gain_min',min(dc),'dc_gain_max',max(dc));save(fullfile(root,'result.mat'),'result','samples');figure('Visible','off');step(samples);grid on;exportgraphics(gcf,fullfile(root,'result.png'));close(gcf);
