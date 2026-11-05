document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('form').forEach(form=>{
    form.addEventListener('submit',event=>{
      if(!form.checkValidity())return;
      const message=form.dataset.confirm;
      if(message&&!window.confirm(message)){event.preventDefault();return;}
      const local=form.querySelector('[data-offset-source]');
      const target=form.querySelector('[data-offset-target]');
      if(local&&target){
        const date=new Date(local.value);
        if(!local.value||Number.isNaN(date.getTime())){event.preventDefault();window.alert('Select a valid date and time');return;}
        // ISO 8601 UTC offset is accepted by the server and normalized to UTC.
        target.value=date.toISOString();
      }
      const button=form.querySelector('button[type="submit"],button:not([type])');
      if(button)button.disabled=true;
    });
  });
});
